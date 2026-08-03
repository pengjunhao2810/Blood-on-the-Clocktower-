"""
邪恶方 ML 策略网络 — REINFORCE 策略梯度
状态编码 → MLP 策略网络 → 动作选择 → 梯度更新（基于对局结果）
"""
from __future__ import annotations
import random
from collections import defaultdict
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from .roles import BOTC_ROLES, BOTC_TEAMS

MAX_PLAYERS = 8
FEAT_DIM = 10
HIDDEN_SIZE = 128


def _get_claim(game, name: str) -> str:
    claim = getattr(game, "public_claims", {}).get(name, "")
    if claim:
        return claim
    for agent in game.registry.all_agents():
        for entry in agent.game_state.get("chat_memory", []):
            if entry.get("speaker") == name:
                txt = entry.get("text", "")
                for rn in BOTC_ROLES:
                    if f"我是{rn}" in txt:
                        return rn
    return ""


def _claim_category(claim: str) -> int:
    if not claim:
        return 0
    if claim in BOTC_TEAMS["townsfolk"]:
        return 1
    if claim in BOTC_TEAMS["outsider"]:
        return 2
    if claim in BOTC_TEAMS["minion"]:
        return 3
    if claim in BOTC_TEAMS["demon"]:
        return 4
    return 0


def encode_observation(game, observer):
    """
    从 observer 视角编码全局状态。
    Returns:
        obs: Tensor (MAX_PLAYERS, FEAT_DIM)
        name_to_idx: dict {name: row_index}
        idx_to_name: list [name0, name1, ...]
    """
    alive = [a for a in game.registry.all_agents() if a.alive]
    dead = [a for a in game.registry.all_agents() if not a.alive]
    all_players = sorted(alive + dead, key=lambda x: x.name)[:MAX_PLAYERS]

    name_to_idx = {p.name: i for i, p in enumerate(all_players)}
    idx_to_name = [p.name for p in all_players]

    gs = observer.game_state
    known = gs.get("known_info", {})
    suspicion = gs.get("suspicion", {})
    trust = gs.get("trust", {})

    demon_name = known.get("demon", "")
    minions = set(known.get("minions", []))

    features = []
    for p in all_players:
        feats = [0.0] * FEAT_DIM
        feats[0] = 1.0 if p.alive else 0.0
        feats[1] = 1.0 if p.name == observer.name else 0.0

        is_demon = p.role in BOTC_TEAMS["demon"]
        is_minion = p.role in BOTC_TEAMS["minion"]
        if observer.name == p.name:
            feats[2], feats[3], feats[4] = 0, 0, 1
        elif demon_name == p.name or p.name in minions:
            feats[2], feats[3], feats[4] = 1, 0, 0
        elif is_demon or (is_minion and demon_name):
            feats[2], feats[3], feats[4] = 1, 0, 0
        else:
            feats[2], feats[3], feats[4] = 0, 0, 1

        feats[5] = suspicion.get(p.name, 50) / 100.0
        feats[6] = trust.get(p.name, 50) / 100.0

        claim = _get_claim(game, p.name)
        feats[7] = 1.0 if claim else 0.0
        feats[8] = _claim_category(claim) / 4.0
        feats[9] = 1.0 if p.role == "士兵" and p.alive else 0.0

        features.append(feats)

    while len(features) < MAX_PLAYERS:
        features.append([-1.0] * FEAT_DIM)

    obs = torch.tensor(features, dtype=torch.float32)
    return obs, name_to_idx, idx_to_name


class EvilPolicy(nn.Module):
    def __init__(self, n_players=MAX_PLAYERS, hidden=HIDDEN_SIZE):
        super().__init__()
        self.n_players = n_players
        self.net = nn.Sequential(
            nn.Linear(n_players * FEAT_DIM, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
        )
        self.kill_head = nn.Linear(hidden // 2, n_players)
        self.vote_head = nn.Linear(hidden // 2, 1)
        self.nominate_head = nn.Linear(hidden // 2, n_players)

    def forward(self, state):
        b = state.shape[0]
        x = state.view(b, -1)
        h = self.net(x)
        return self.kill_head(h), self.vote_head(h), self.nominate_head(h)

    def _masked_dist(self, logits, valid_indices):
        n = logits.shape[-1]
        mask = torch.full((n,), -float('inf'), device=logits.device)
        if valid_indices:
            for i in valid_indices:
                if i < n:
                    mask[i] = logits[0, i]
        else:
            mask[:n] = logits[0, :n]
        return torch.distributions.Categorical(F.softmax(mask, dim=-1))

    def act_kill(self, state, valid_kill=None, eps=0.2):
        kl, _, _ = self.forward(state.unsqueeze(0))
        if random.random() < eps and valid_kill:
            return random.choice(valid_kill), None
        dist = self._masked_dist(kl, valid_kill)
        idx = dist.sample()
        return idx.item(), dist.log_prob(idx)

    def act_nominate(self, state, valid_nom=None, eps=0.2):
        _, _, nl = self.forward(state.unsqueeze(0))
        if random.random() < eps and valid_nom:
            return random.choice(valid_nom), None
        dist = self._masked_dist(nl, valid_nom)
        idx = dist.sample()
        return idx.item(), dist.log_prob(idx)

    def get_vote_probs(self, state):
        _, vl, _ = self.forward(state.unsqueeze(0))
        return torch.sigmoid(vl[0, 0])

    def sample_vote(self, state, record_cb=None):
        prob = self.get_vote_probs(state)
        dist = torch.distributions.Bernoulli(prob)
        action = dist.sample()
        if record_cb is not None:
            record_cb(dist.log_prob(action))
        return action.item()

    def get_entropy(self, state):
        logits_k, logits_v, logits_n = self.forward(state.unsqueeze(0))
        pk = F.softmax(logits_k, dim=-1)
        pn = F.softmax(logits_n, dim=-1)
        pv = torch.sigmoid(logits_v)
        eps = 1e-8
        ent_k = -(pk * (pk + eps).log()).sum(dim=-1).mean()
        ent_n = -(pn * (pn + eps).log()).sum(dim=-1).mean()
        ent_v = -(pv * (pv + eps).log() + (1 - pv) * ((1 - pv) + eps).log()).mean()
        return (ent_k + ent_n + ent_v) / 3.0


class REINFORCETrainer:
    def __init__(self, policy, lr=1e-4, gamma=0.95, entropy_coef=0.05):
        self.policy = policy
        self.optimizer = torch.optim.Adam(policy.parameters(), lr=lr)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, step_size=5, gamma=0.8)
        self.gamma = gamma
        self.entropy_coef = entropy_coef
        self.trajectory: list[torch.Tensor] = []
        self.step_rewards: list[float] = []  # P2/P3: 过程奖励
        self.total_steps = 0
        self.baseline = 0.0
        self.baseline_decay = 0.9

    def record_step(self, log_prob: torch.Tensor, reward: float = 0.0):
        self.trajectory.append(log_prob)
        self.step_rewards.append(reward)

    def finish_episode(self, win: bool) -> float:
        final_reward = 1.0 if win else -1.0
        if not self.trajectory:
            return 0.0

        # P2/P3: 合并过程奖励 + 最终胜负奖励
        rewards = list(self.step_rewards)
        if rewards:
            rewards[-1] += final_reward  # 最终奖励叠加在最后一步
        else:
            rewards = [final_reward] * len(self.trajectory)

        returns = []
        R = 0.0
        for r in reversed(rewards):
            R = r + self.gamma * R
            returns.insert(0, R)
        returns_t = torch.tensor(returns)

        returns_t = returns_t - self.baseline
        self.baseline = self.baseline_decay * self.baseline + (1 - self.baseline_decay) * (sum(returns) / len(returns))

        if returns_t.std() > 1e-8:
            returns_t = returns_t / (returns_t.std() + 1e-8)

        pg_loss = sum(-lp * Rval for lp, Rval in zip(self.trajectory, returns_t))

        if self.entropy_coef > 0:
            with torch.no_grad():
                entropy = self.policy.get_entropy(
                    torch.zeros(1, MAX_PLAYERS, FEAT_DIM)
                )
            ent_loss = -self.entropy_coef * entropy
            total_loss = pg_loss + ent_loss
        else:
            total_loss = pg_loss

        self.optimizer.zero_grad()
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy.parameters(), 1.0)
        self.optimizer.step()
        self.scheduler.step()

        self.total_steps += 1
        n = len(self.trajectory)
        self.trajectory.clear()
        self.step_rewards.clear()
        return total_loss.item() / n


# 全局状态
_policy: Optional[EvilPolicy] = None
_trainer: Optional[REINFORCETrainer] = None
_eps = 0.2
_record = False
_pending_reward = 0.0  # P2/P3: 过程奖励累加器


def add_reward(val: float):
    """游戏过程中加分/减分，下次record_step时合并"""
    global _pending_reward
    _pending_reward += val


def consume_reward() -> float:
    """取走并清零过程奖励"""
    global _pending_reward
    r = _pending_reward
    _pending_reward = 0.0
    return r


def get_policy():
    global _policy
    if _policy is None:
        _policy = EvilPolicy()
    return _policy


def get_trainer():
    global _trainer
    if _trainer is None:
        _trainer = REINFORCETrainer(get_policy())
    return _trainer


def set_epsilon(eps: float):
    global _eps
    _eps = eps


def set_enabled(enabled: bool):
    global _ml_enabled
    _ml_enabled = enabled


_ml_enabled = True  # 默认启用 ML


def is_enabled():
    return _ml_enabled


def set_record(active: bool):
    global _record
    _record = active


def is_recording():
    return _record


def reset():
    global _policy, _trainer
    _policy = None
    _trainer = None
