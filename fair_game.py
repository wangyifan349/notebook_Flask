import hashlib
import os
import random

def make_commit(value, salt):
    """生成 SHA256 承诺值"""
    return hashlib.sha256(f"{value}|{salt}".encode()).hexdigest()

class BotA:
    """负责每轮动作与押注方向选择，并生成承诺"""
    def __init__(self):
        pass

    def decide(self):
        action = random.choice(["A", "B"])
        direction = random.choice(["大", "小"])
        return action, direction

    def commit(self, action, direction):
        a_salt = os.urandom(8).hex()
        d_salt = os.urandom(8).hex()
        a_commit = make_commit(action, a_salt)
        d_commit = make_commit(direction, d_salt)
        return (a_commit, a_salt, action), (d_commit, d_salt, direction)

class BotB:
    """负责每轮下注协商与最终结果公示"""
    def negotiate_bet(self, user_chips, bot_chips):
        while True:
            bet = int(input(f"请输入本轮下注（1–{min(user_chips, bot_chips)}）："))
            if 1 <= bet <= user_chips and bet <= bot_chips:
                print(f"BotB：双方同意本轮下注 {bet} 筹码。")
                return bet
            print("BotB：下注不合法，请重新输入。")

    def announce_commits(self, uc, dc, bc, bd):
        print("\nBotB 发布承诺：")
        print(f"  用户动作承诺：{uc}")
        print(f"  用户方向承诺：{dc}")
        print(f"  机器人动作承诺：{bc}")
        print(f"  机器人方向承诺：{bd}")

    def announce_reveal(self, bot_action, bot_asalt, bot_direction, bot_dsalt):
        print("\nBotB 公示机器人揭示：")
        print(f"  机器人动作：{bot_action}（盐：{bot_asalt}）")
        print(f"  机器人方向：{bot_direction}（盐：{bot_dsalt}）")

    def announce_result(self, winner, user_chips, bot_chips):
        print(f"\nBotB 公示本回合胜者：{winner}")
        print(f"BotB 更新筹码：用户 {user_chips} — 机器人 {bot_chips}\n")

def play_round(user_chips, bot_chips, botA, botB):
    # 1. 协商下注
    bet = botB.negotiate_bet(user_chips, bot_chips)

    # 2. 用户输入阶段
    user_action = input("用户，请选择动作 A/B：").strip().upper()
    user_a_salt = os.urandom(8).hex()
    user_a_commit = make_commit(user_action, user_a_salt)

    user_direction = input("用户，请选择押注方向 大/小：").strip()
    user_d_salt = os.urandom(8).hex()
    user_d_commit = make_commit(user_direction, user_d_salt)

    # 3. BotA 选择并承诺
    bot_action, bot_direction = botA.decide()
    (bot_a_commit, bot_a_salt, _), (bot_d_commit, bot_d_salt, _) = botA.commit(bot_action, bot_direction)

    # 4. BotB 发布承诺
    botB.announce_commits(user_a_commit, user_d_commit, bot_a_commit, bot_d_commit)

    # 5. 用户揭示并验证
    r_action = input("用户揭示动作 A/B：").strip().upper()
    r_asalt  = input("用户动作盐值：").strip()
    if make_commit(r_action, r_asalt) != user_a_commit:
        print("用户动作校验失败，本回合作废。")
        return user_chips, bot_chips
    r_direction = input("用户揭示方向 大/小：").strip()
    r_dsalt     = input("用户方向盐值：").strip()
    if make_commit(r_direction, r_dsalt) != user_d_commit:
        print("用户方向校验失败，本回合作废。")
        return user_chips, bot_chips

    # 6. BotB 公示机器人揭示并验证
    botB.announce_reveal(bot_action, bot_a_salt, bot_direction, bot_d_salt)
    assert make_commit(bot_action, bot_a_salt) == bot_a_commit, "机器人动作校验失败"
    assert make_commit(bot_direction, bot_d_salt) == bot_d_commit, "机器人方向校验失败"

    # 7. 结果判定：A 赢 B 输，平局返还
    if r_action == bot_action:
        winner = "平局"
    elif r_action == "A":
        winner = "用户"
    else:
        winner = "机器人"

    # 8. 筹码结算
    if winner == "平局":
        pass
    else:
        # 用户押“大”视为猜 winner=="用户”，押“小”视为猜 winner=="机器人”
        guess_user = (r_direction == "大")
        correct = (winner == "用户") == guess_user
        if correct:
            user_chips += bet
            bot_chips  -= bet
        else:
            user_chips -= bet
            bot_chips  += bet

    # 9. BotB 公示结果
    botB.announce_result(winner, user_chips, bot_chips)
    return user_chips, bot_chips

def main():
    botA = BotA()
    botB = BotB()
    user_chips = bot_chips = 100
    rounds = int(input("请输入总回合数："))

    for i in range(1, rounds+1):
        print(f"\n=== 第 {i} 回合（筹码：{user_chips} vs {bot_chips}）===")
        user_chips, bot_chips = play_round(user_chips, bot_chips, botA, botB)
        if user_chips <= 0 or bot_chips <= 0:
            break

    print("\n=== 全部回合结束 ===")
    if user_chips > bot_chips:
        print(f"最终胜者：用户（{user_chips} vs {bot_chips}）")
    elif bot_chips > user_chips:
        print(f"最终胜者：机器人（{bot_chips} vs {user_chips}）")
    else:
        print(f"最终平局（{user_chips} vs {bot_chips}）")

if __name__ == "__main__":
    main()
