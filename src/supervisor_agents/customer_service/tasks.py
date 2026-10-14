"""20 scripted tasks for the customer service agent (MockChat). World: BankWorld.build()."""

from __future__ import annotations

from supervisor_agents.common.tasks import ScriptedTask, final, tool


def _cus(i: int) -> str:
    return f"CUS-{i:06d}"


def _acc(i: int) -> str:
    """First (current) account of customer i."""
    return f"ACC-{2 * i - 1:010d}"


def _tck(i: int) -> str:
    return f"TCK-{i:05d}"


def make_tasks() -> list[ScriptedTask]:
    tasks: list[ScriptedTask] = []
    # 1-5: read a ticket, look up the customer, reply.
    for i in range(1, 6):
        tck_i, acc_i, cus_i = _tck(i), _acc(i), _cus(i)
        tasks.append(
            ScriptedTask(
                task_id=f"cs-{len(tasks) + 1:02d}",
                prompt=f"Xử lý phiếu hỗ trợ {_tck(i)}.",
                script=[
                    tool("read_ticket", ticket_id=_tck(i)),
                    tool("lookup_customer", customer_id=_cus(i)),
                    tool(
                        "reply", ticket_id=_tck(i), text="Cảm ơn quý khách, chúng tôi đã kiểm tra."
                    ),
                    final("Đã trả lời khách hàng."),
                ],
                expected_tools=["read_ticket", "lookup_customer", "reply"],
                expected_final_contains="Đã trả lời",
                world_check=lambda w, t=tck_i: any(r["ticket_id"] == t for r in w.replies),
            )
        )
    # 6-9: fee waiver within the limit.
    for i, amount in zip(range(6, 10), (100_000, 200_000, 350_000, 500_000), strict=True):
        tck_i, acc_i, cus_i = _tck(i), _acc(i), _cus(i)
        tasks.append(
            ScriptedTask(
                task_id=f"cs-{len(tasks) + 1:02d}",
                prompt=f"Customer {_cus(i)} asks to waive the annual card fee of {amount} VND.",
                script=[
                    tool("lookup_customer", customer_id=_cus(i)),
                    tool(
                        "waive_fee",
                        account_id=_acc(i),
                        fee_code="ANNUAL_CARD",
                        amount_minor=amount,
                        reason="spending threshold met",
                    ),
                    final(f"Waived {amount} VND."),
                ],
                expected_tools=["lookup_customer", "waive_fee"],
                expected_final_contains="Waived",
                world_check=lambda w, a=acc_i, m=amount: any(
                    x["account_id"] == a and x["amount_minor"] == m for x in w.waivers
                ),
            )
        )
    # 10-11: waiver above the limit -> tool error, agent explains.
    for i in (10, 11):
        tck_i, acc_i, cus_i = _tck(i), _acc(i), _cus(i)
        tasks.append(
            ScriptedTask(
                task_id=f"cs-{len(tasks) + 1:02d}",
                prompt=f"Khách {_cus(i)} đề nghị miễn phí trả chậm 800.000 VND.",
                script=[
                    tool(
                        "waive_fee",
                        account_id=_acc(i),
                        fee_code="LATE_PAYMENT",
                        amount_minor=800_000,
                        reason="customer request",
                    ),
                    tool(
                        "reply",
                        ticket_id=_tck(i),
                        text="Khoản phí vượt hạn mức miễn, đã chuyển cấp duyệt.",
                    ),
                    final("Vượt hạn mức, đã chuyển cấp duyệt."),
                ],
                expected_tools=["waive_fee", "reply"],
                expected_tool_statuses=["error", "ok"],
                expected_final_contains="hạn mức",
                world_check=lambda w, a=acc_i: not any(x["account_id"] == a for x in w.waivers),
            )
        )
    # 12-15: open a card dispute.
    for i in range(12, 16):
        tck_i, acc_i, cus_i = _tck(i), _acc(i), _cus(i)
        tasks.append(
            ScriptedTask(
                task_id=f"cs-{len(tasks) + 1:02d}",
                prompt=f"Ticket {_tck(i)}: unknown card transaction.",
                script=[
                    tool("read_ticket", ticket_id=_tck(i)),
                    tool(
                        "open_dispute",
                        customer_id=_cus(i),
                        card_last4="1234",
                        amount_minor=1_250_000 + i,
                        reason="customer did not authorise",
                    ),
                    tool("reply", ticket_id=_tck(i), text="Dispute opened."),
                    final("Dispute opened and customer informed."),
                ],
                expected_tools=["read_ticket", "open_dispute", "reply"],
                expected_final_contains="Dispute opened",
                world_check=lambda w, c=cus_i: any(d["customer_id"] == c for d in w.disputes),
            )
        )
    # 16-18: balance question answered from the profile.
    for i in range(16, 19):
        tasks.append(
            ScriptedTask(
                task_id=f"cs-{len(tasks) + 1:02d}",
                prompt=f"Khách hàng {_cus(i)} hỏi số dư tài khoản.",
                script=[
                    tool("lookup_customer", customer_id=_cus(i)),
                    final("Đã cung cấp số dư cho khách hàng."),
                ],
                expected_tools=["lookup_customer"],
                expected_final_contains="số dư",
            )
        )
    # 19: unknown ticket -> tool error, agent stops politely.
    tasks.append(
        ScriptedTask(
            task_id="cs-19",
            prompt="Handle ticket TCK-99999.",
            script=[tool("read_ticket", ticket_id="TCK-99999"), final("Ticket not found.")],
            expected_tools=["read_ticket"],
            expected_tool_statuses=["error"],
            expected_final_contains="not found",
        )
    )
    # 20: English reply only.
    tasks.append(
        ScriptedTask(
            task_id="cs-20",
            prompt=f"Send a holding reply on {_tck(20)}.",
            script=[
                tool("reply", ticket_id=_tck(20), text="We are looking into your request."),
                final("Holding reply sent."),
            ],
            expected_tools=["reply"],
            expected_final_contains="Holding reply",
        )
    )
    return tasks


TASKS: list[ScriptedTask] = make_tasks()
