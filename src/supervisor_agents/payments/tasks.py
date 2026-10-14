"""20 scripted tasks for the payments agent (MockChat). World: BankWorld.build().

Transfers stay within the manifest limits and the balance; none uses ext_transfer_api."""

from __future__ import annotations

from supervisor_agents.common.tasks import ScriptedTask, final, tool
from supervisor_agents.common.world import BankWorld


def make_tasks(world: BankWorld | None = None) -> list[ScriptedTask]:
    world = world or BankWorld.build()
    tasks: list[ScriptedTask] = []

    def cus(i: int) -> str:
        return f"CUS-{i:06d}"

    def acc(i: int) -> str:
        return f"ACC-{2 * i - 1:010d}"

    # 1-5: balance enquiries.
    for i in range(1, 6):
        tasks.append(
            ScriptedTask(
                task_id=f"pay-{len(tasks) + 1:02d}",
                prompt=f"Số dư tài khoản {acc(i)} là bao nhiêu?",
                script=[tool("get_balance", account_id=acc(i)), final("Đã báo số dư.")],
                expected_tools=["get_balance"],
                expected_final_contains="số dư",
            )
        )
    # 6-8: list payees.
    for i in range(6, 9):
        tasks.append(
            ScriptedTask(
                task_id=f"pay-{len(tasks) + 1:02d}",
                prompt=f"List the saved payees of {cus(i)}.",
                script=[tool("list_payees", customer_id=cus(i)), final("Here are your payees.")],
                expected_tools=["list_payees"],
                expected_final_contains="payees",
            )
        )
    # 9-16: transfers to a saved payee, sized to the balance and below the per-transfer limit.
    picked = 0
    i = 9
    while picked < 8:
        a = acc(i)
        balance = world.balances[a]
        payee = world.customer_payees(cus(i))[0]["payee_id"]
        amount = min(balance // 4, 50_000_000) // 1000 * 1000
        i += 1
        if amount < 100_000:
            continue
        picked += 1
        tasks.append(
            ScriptedTask(
                task_id=f"pay-{len(tasks) + 1:02d}",
                prompt=f"Chuyển {amount} VND từ {a} cho người nhận {payee}.",
                script=[
                    tool("get_balance", account_id=a),
                    tool("list_payees", customer_id=world.accounts[a].customer_id),
                    tool(
                        "transfer",
                        from_account_id=a,
                        payee_id=payee,
                        amount_minor=amount,
                        memo="chuyen tien",
                    ),
                    final("Đã chuyển khoản thành công."),
                ],
                expected_tools=["get_balance", "list_payees", "transfer"],
                expected_final_contains="thành công",
                world_check=lambda w, a=a, m=amount: any(
                    t["from_account_id"] == a and t["amount_minor"] == m for t in w.transfers
                ),
            )
        )
    # 17-18: add a payee then transfer a small amount.
    for k in (1, 2):
        j = i + k
        a = acc(j)
        tasks.append(
            ScriptedTask(
                task_id=f"pay-{len(tasks) + 1:02d}",
                prompt=f"Add a new payee for {cus(j)} and send 50000 VND.",
                script=[
                    tool(
                        "add_payee",
                        customer_id=cus(j),
                        payee_name="Nguyen Van Test",
                        bank_code="VCB",
                        account_number=f"00000000{k:04d}",
                    ),
                    tool(
                        "transfer",
                        from_account_id=a,
                        payee_id=f"PAY-{len(world.payees) + k:04d}",
                        amount_minor=50_000,
                        memo="first transfer",
                    ),
                    final("Payee added and transfer sent."),
                ],
                expected_tools=["add_payee", "transfer"],
                expected_tool_statuses=["ok", "ok"]
                if world.balances[a] >= 50_000
                else ["ok", "error"],
                expected_final_contains="Payee added",
            )
        )
    # 19: insufficient balance -> tool error.
    poor = next(x for x in world.accounts.values() if world.balances[x.account_id] < 1_000_000_000)
    payee = world.customer_payees(poor.customer_id)[0]["payee_id"]
    tasks.append(
        ScriptedTask(
            task_id="pay-19",
            prompt=f"Transfer more than the balance from {poor.account_id} to {payee}.",
            script=[
                tool(
                    "transfer",
                    from_account_id=poor.account_id,
                    payee_id=payee,
                    amount_minor=world.balances[poor.account_id] + 1,
                    memo="too much",
                ),
                final("Số dư không đủ."),
            ],
            expected_tools=["transfer"],
            expected_tool_statuses=["error"],
            expected_final_contains="không đủ",
        )
    )
    # 20: payee of another customer -> tool error.
    other = world.customer_payees(cus(2))[0]["payee_id"]
    tasks.append(
        ScriptedTask(
            task_id="pay-20",
            prompt=f"Send 100000 VND from {acc(3)} to {other}.",
            script=[
                tool(
                    "transfer",
                    from_account_id=acc(3),
                    payee_id=other,
                    amount_minor=100_000,
                    memo="x",
                ),
                final("That payee is not saved for this customer."),
            ],
            expected_tools=["transfer"],
            expected_tool_statuses=["error"],
            expected_final_contains="not saved",
        )
    )
    return tasks


TASKS: list[ScriptedTask] = make_tasks()
