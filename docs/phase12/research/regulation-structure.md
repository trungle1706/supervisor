# Regulation structure: risk classes and risk aspects (VN AI stack, as stored in RegKB)

Sources: the four stored texts under `/home/trung/supervisor/regulations/sources/` (`VN-AI-2025`, `VN-DEC142-2026`, `VN-QD33-2026`, `VN-TT53-2026/53-2026-tt-nhnn.txt`, vbpl text of record). Not legal advice; only what the texts say.

## 1. Risk classification

### 1.1 All levels and gates

The Law defines exactly three levels. No "unclassified" level, no foundation-model class, no state-agency class. Around them: one bar (prohibited practices), one split inside "high", one extra duty for state agencies.

| # | Level / gate | Source | Quote |
|---|---|---|---|
| 0 | Prohibited practice (a bar, not a level) | Law Art. 7(2)(b)-(d) | "lừa dối hoặc thao túng nhận thức, hành vi của con người"; "Lợi dụng điểm yếu của nhóm người dễ bị tổn thương"; "nội dung giả mạo có khả năng gây nguy hại nghiêm trọng" |
| 1 | High | Law Art. 9(1)(a); Decree Art. 6(3)(a) | "có thể gây thiệt hại đáng kể đến tính mạng, sức khỏe, quyền và lợi ích hợp pháp"; in practice "thuộc Danh mục... do Thủ tướng Chính phủ ban hành" |
| 1a | High, certification before use | Law Art. 13(2)(a); Decree Art. 7(1)(b) | "phải chứng nhận sự phù hợp trước khi đưa vào sử dụng" |
| 1b | High, self-assessment or registered body | Law Art. 13(2)(b) | "nhà cung cấp tự đánh giá sự phù hợp hoặc thuê tổ chức đánh giá" (both banking rows of Decision 33 Appendix IV sit in this column) |
| 2 | Medium | Law Art. 9(1)(b); Decree Art. 9(1) | "gây nhầm lẫn, tác động hoặc thao túng người sử dụng do không nhận biết được chủ thể tương tác là hệ thống trí tuệ nhân tạo" and not in the high list |
| 3 | Low | Law Art. 9(1)(c) | "không thuộc trường hợp quy định tại điểm a và điểm b" (residual) |
| - | Level not determinable (procedure) | Law Art. 10(4) | "nhà cung cấp được đề nghị Bộ Khoa học và Công nghệ hướng dẫn" |
| - | Bare models: not classified | Decree Art. 6(2) | "không áp dụng đối với mô hình trí tuệ nhân tạo, trừ trường hợp mô hình được sử dụng như một thành phần của hệ thống" |
| - | State-agency use: extra impact assessment | Decree Art. 20(1), 20(7) | high-risk systems, or output "làm căn cứ trực tiếp để người có thẩm quyền... ban hành quyết định hành chính" |

"Mô hình nền tảng, mô hình trí tuệ nhân tạo đa dụng" appear only in Law Art. 16(3), not as a class.

### 1.2 Criteria

| Source | Content |
|---|---|
| Law Art. 9(2) | "mức độ tác động đến quyền con người, an toàn, an ninh; lĩnh vực sử dụng...; phạm vi người sử dụng và quy mô ảnh hưởng" |
| Decree Art. 8(1)(a)-(c) | impact incl. "mức độ tự động của hệ thống; mức độ hỗ trợ ra quyết định cuối cùng"; essential sector; scale |
| Decree Art. 8(2)(a)-(d) exclusions from high list | data-only tasks; human able to "từ chối hoặc thay đổi quyết định của hệ thống trước khi quyết định đó có hiệu lực"; internal-only use; advisory output not "căn cứ duy nhất" |
| Decision 33 App. IV.1 (auto e-transactions), 3 cumulative | "tự tạo, sửa đổi, xác nhận và phê duyệt giao dịch"; "mức giá trị cao theo quy định của Ngân hàng Nhà nước"; "Không có sự kiểm tra, phê duyệt hoặc kiểm soát của con người trước khi giao dịch được thực hiện" |
| Decision 33 App. IV.2 (auto credit), 3 cumulative | "quyết định cuối cùng về việc phê duyệt hoặc từ chối cấp tín dụng"; "không có sự phê duyệt độc lập của cán bộ tín dụng"; loan value per SBV |
| Decree Art. 9(3)(a)-(đ) exclusions from medium | cosmetic editing; obvious office tools; not public-facing; art/games; back-end processing |

### 1.3 Circular 53 Art. 4(2): SBV thresholds and bank sub-categories

Art. 4(1): "đơn vị phải thực hiện phân loại hệ thống trí tuệ nhân tạo theo mức độ rủi ro cao, trung bình, thấp".

| Trigger | Art. 4(2) threshold |
|---|---|
| Auto payment, personal customer | "lớn hơn 10 triệu đồng hoặc... trong một ngày... lớn hơn 20 triệu đồng" |
| Auto payment, organisation | "lớn hơn 50 triệu đồng hoặc... trong một ngày... lớn hơn 100 triệu đồng" |
| Auto credit decision | "có xử lý khoản cấp tín dụng có giá trị từ 50 triệu đồng trở lên" |

Sub-categories that scale duties (not formal levels):

| Sub-category | Article | Effect |
|---|---|---|
| Decides vs supports: "để ra quyết định hoặc hỗ trợ ra quyết định" | 1(1)(a) | both in scope |
| "rủi ro trung bình ra quyết định trong hoạt động nghiệp vụ" | 6(1)(b), 8(3)(b), 16(1) | OWASP controls, vendor-model change impact, model validation |
| Auto payment / auto credit | 5(1)(g), 5(1)(h) | biometric agreement, cap "không vượt quá 100 triệu đồng... 500 triệu đồng", customer kill-switch |
| Customer-facing: replaces a human (20(3)) or decides with legal/financial effect (20(5)) | 20(3), 20(5) | disclose AI "ngay từ khi bắt đầu phiên làm việc"; store and explain decision basis |
| Generative / LLM | 6(1)(a)(iii), 6(1)(b) | prompt-injection, hallucination, output-bias tests |
| Third-party model via API | 16(3)(b), 8(3)(b) | black-box test on bank data, fallback plan |
| Internal governance systems; personal non-integrated tools | 1(1)(b), 1(1)(c) | "Khuyến khích áp dụng" only; out of scope |

### 1.4 Who classifies, re-classification, order of steps

Who: the provider self-classifies before use and "chịu trách nhiệm trước pháp luật về tính chính xác, trung thực" (Law 10(1); Decree 6(1)). The deployer "được kế thừa kết quả phân loại của nhà cung cấp" (Law 10(2); Circular 4(4)). Bank: result "phải được phê duyệt bởi cấp có thẩm quyền của đơn vị" (4(3)); inventory reviewed "tối thiểu hằng năm" (4(5)).

Re-classification: Decree 11(1)(a)-(d): change of "chức năng, mục đích sử dụng hoặc ngữ cảnh triển khai"; serious incident showing "mức độ rủi ro thực tế cao hơn"; list amended; regulator demand. Deployer changes "làm phát sinh rủi ro mới hoặc rủi ro cao hơn" (Decree 5(3), 6(4), 11(2)). Not triggers: "sửa lỗi kỹ thuật thông thường hoặc cập nhật dữ liệu định kỳ" (11(4)). Upward: notify in "15 ngày làm việc" (11(3)(a)); 12-month transition if a list change makes it high (11(5)). "Thay đổi đáng kể" = Decree 13(1)(a)-(đ). Bank adds: after a serious incident "đánh giá lại mức độ rủi ro... thực hiện phân loại lại" (Circular 9(4)); impact assessment updated on change (13(2)); re-validation "khi mức độ rủi ro của hệ thống thay đổi" (16(2)(c)).

Decision steps (Decree 6(3), 9; Law 10):
1. System, not a bare model (Decree 6(2)).
2. Prohibited use (Law 7)? Stop.
3. In the PM list with all row conditions and SBV thresholds met? HIGH; note conformity column.
4. Else can it confuse users about AI nature/content (Law 9(1)(b)) and not excluded by Decree 9(3)? MEDIUM.
5. Else LOW.
6. High/medium: dossier (Decree 12(2)), notify MOST before use (Law 10(3)).
7. High: conformity assessment (Law 13(1)); bank: impact assessment (Circular 13), board go-live approval (12(3)).
8. Bank: approve level, record in inventory (4(3), 4(5)).

## 2. Risk aspects the bank must assess

### 2.1 The mandatory named list

Circular Art. 14(3): "Các loại rủi ro... được quản lý tối thiểu bao gồm" eight types. Art. 14(4): for each the bank sets "nội hàm, tiêu chí nhận dạng, phương pháp đo lường, ngưỡng chấp nhận và biện pháp kiểm soát". Art. 14 applies from 2027-01-01 (Art. 23(2)).

| # | Type (Art. 14(3)) | Detail articles | Nature |
|---|---|---|---|
| 1 | "Rủi ro mô hình" | 16(3): data fit, algorithm, accuracy, explainability, "Tính công bằng và kiểm soát nguy cơ thiên lệch", robustness; 16(5) drift | assessment + monitoring |
| 2 | "Rủi ro quản trị dữ liệu" | 7(2) provenance, synthetic data; 7(3) quality, "dữ liệu... bị thao túng hoặc bị đầu độc", data drift; 7(4) leakage/least privilege | control + monitoring |
| 3 | "Rủi ro an ninh mạng" | 6(1)(a): privacy leakage; poisoning, evasion, extraction (mandatory high risk); "Tấn công tiêm lệnh, rủi ro tạo sinh nội dung sai lệch" (generative); 6(1)(b) OWASP | assessment + control |
| 4 | "Rủi ro tuân thủ pháp luật" | 3(1); 7(1); 5(1)(a); 13(1)(c) DPIA "nếu có" | assessment |
| 5 | "Rủi ro đạo đức" | 17(1) "thiên lệch dữ liệu, thiên lệch mô hình và thiên lệch vận hành; ... nhóm dễ bị tổn thương"; 17(2)/13(1)(b) "tính công bằng, sự minh bạch, khả năng giải thích và nguy cơ phân biệt đối xử" | assessment (high) + control |
| 6 | "Rủi ro từ bên thứ ba" | 18(2)(a) vendor assessment; 18(3) contract (SOC 2/ISO 27001/42001, logs/API, no training on bank data); 18(4)(đ) platform dependence | assessment + control + monitoring |
| 7 | "Rủi ro chuỗi cung ứng" | 19(1) libraries/datasets/pre-trained models; 19(2) component inventory; 19(3) integrity; 19(5) "tối thiểu hằng năm" for high risk | control + periodic assessment |
| 8 | "Rủi ro danh tiếng (đối với ngân hàng thương mại và chi nhánh ngân hàng nước ngoài)" | 14(3) only | assessment, bank-defined |

### 2.2 Cross-cutting dimensions also required

| Dimension | Source | Nature |
|---|---|---|
| Operational / business risk | 13(1)(b) "rủi ro tiềm ẩn đối với hoạt động nghiệp vụ"; 3(2) | assessment |
| Customer harm / consumer rights | 13(1)(b) "quyền lợi của khách hàng"; 20(2)-(5); 18(4)(e) remedy | assessment + control |
| Personal data | 13(1)(c) "Đánh giá tác động xử lý dữ liệu cá nhân"; 9(2)(d) notify customers | assessment + control |
| Continuity / incident | 3(4) "tính liên tục"; 22(2)(e); 9 | control |
| Financial exposure / limits | 5(1)(g)(ii) caps; 5(1)(c) "ngưỡng rủi ro, tiêu chí cảnh báo" | control |
| Human oversight | 5(2) "cơ chế ngắt khẩn cấp"; Decree 15(2)(a), 15(5)(c) | control + logging |

### 2.3 Count and shortest defensible list

Mandatory named types: 8 (7 for non-bank units; reputation is bank-only). The Art. 13(1) impact-assessment items (operations, cyber, customer rights with fairness/explainability/discrimination, personal data) are mandatory for high risk but map as sub-items: cyber to 3, fairness to 5, personal data to 4.

Shortest defensible product list: **Model, Data governance, Cybersecurity (incl. prompt injection), Legal compliance (incl. personal data), Ethics/bias, Third party, Supply chain, Reputation** = 8 statuses; optional ninth row "Customer harm / operations" from Art. 13(1)(b).

## 3. RegKB YAML: encoded vs not

Encoded: `risk_classification` on Law 9(1), 10(1)-(3); Decree 5(3), 6(4), 8(2)(b), 11(1), 11(3)(a), 11(5), 12(6); QD33 Art. 2 and all 6 Appendix IV conditions; TT53 4(1)-(3), 9(4). Also `transaction_limits`, `model_inventory`, `conformity_assessment`, `risk_management_system`, `independent_validation` (16, 22), `bias_monitoring`/`fair_treatment`/`dpia`/`explainability` (13(1), 17(1)), `security_testing`/`prompt_injection_defence` (6(1)), `outsourcing_oversight`/`processor_contract`/`supply_chain_security` (18, 19(2)), `business_continuity` (8(3)(b)), `data_quality` (7(2)(c)).

Not encoded:
- TT53 Art. 14(3)-(4), the 8 named risk types with per-type thresholds, exist only as a `notes` sentence on `VN-TT53-2026-A14.02-01`. No obligation row; no duty tags for reputation, legal-compliance or operational risk in the vocabulary.
- No risk-level field: `applies_to` has `agent_class` and `role` only. Medium vs low, "medium that decides", generative/LLM, third-party-model-via-API are not flags.
- Decree 142 absent as rows: 6(2), 6(3), 8(1), 8(2)(a),(c),(d), 9(1), 9(3), 10, 11(4), 12(2), 13(1), 20. Law 9(2), 10(4), 10(5), 7(2)(d) absent.
- TT53 7(2)(a)-(b), 7(3), 19(1), 19(3)-(5), 16(1), 16(3)(b), 18(2)(a), 18(4)(đ), 3(2), 3(4), 22(3): absent or partial.
- Date overrides only in notes: Art. 14 from 2027-01-01; 6(1)(b), 21 from 2027-09-01; Art. 24 from 2027-03-01.
