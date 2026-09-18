package engine

import "testing"

// 死亡票：有票的死亡玩家可投 yes 一次（投出即消耗）；无票死亡玩家拒绝投票
func TestDeadVoteOnceOnly(t *testing.T) {
	e, gd := makeNominateGame(6)
	// 玩家 #2 死亡并获得死亡票
	gd.Players["1"].Alive = false
	gd.Players["1"].DeadVote = true
	gd.Players["1"].IsAI = false
	gd.Players["1"].AIType = ""

	e.Nominate(1, 3)
	e.StartVoting()
	// 死亡玩家 #2 用死亡票投票 → 成功
	_, _, err := e.CastVote(2, "yes")
	if err != nil {
		t.Fatalf("死亡票投票应成功: %v", err)
	}
	// 死亡票已消耗
	if gd.Players["1"].DeadVote {
		t.Fatal("死亡票使用后应被没收")
	}
	// 已消耗死亡票后取消再投 → 拒绝
	_, _, err = e.CastVote(2, "abstain")
	if err != nil {
		t.Fatalf("取消投票应成功: %v", err)
	}
	_, _, err = e.CastVote(2, "yes")
	if err == nil {
		t.Fatal("死亡票已消耗后再次投票应被拒绝")
	}
}

func TestDeadVoteOnlyOneChance(t *testing.T) {
	e, gd := makeNominateGame(6)
	// #2 死亡且无死亡票
	gd.Players["1"].Alive = false
	gd.Players["1"].DeadVote = false

	e.Nominate(1, 3)
	e.StartVoting()
	_, _, err := e.CastVote(2, "yes")
	if err == nil {
		t.Fatal("无死亡票的死亡玩家投票应被拒绝")
	}
}
