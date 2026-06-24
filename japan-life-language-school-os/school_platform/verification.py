from __future__ import annotations

from typing import Any


TEACHER_VERIFICATION_REQUIRED_SCORE = 85.0


def teacher_manual_blueprint() -> dict[str, list[dict[str, Any]]]:
    return {
        "sections": [
            {
                "slug": "platform-ops",
                "title": "平台操作指南",
                "summary": "老師先學會進站後的資料檢視、開課前準備與課後回報節點。",
                "content": "\n".join(
                    [
                        "1. 登入後先查看 AI 老師同步的學員實戰數據與弱點摘要。",
                        "2. 上課前 5 分鐘確認班級權限、教材連結與點名入口都可用。",
                        "3. 下課後 10 分鐘內提交學員口說流暢度追蹤卡與課後紀錄。",
                        "4. 若發現高風險學員，必須在當日同步到教務與學員追蹤系統。",
                    ]
                ),
                "estimated_minutes": 20,
                "required": True,
            },
            {
                "slug": "golden-speaking-sop",
                "title": "黃金口說教學法 SOP",
                "summary": "把平台的大數據教學法落到每一堂真人課。",
                "content": "\n".join(
                    [
                        "1. 真人課禁止單向灌輸文法，必須以情境任務引導開場。",
                        "2. 每堂課至少保留 15 分鐘 Shadowing 影子跟讀。",
                        "3. 學員回答後要即時糾正發音、文法與敬語盲點。",
                        "4. 每堂課都要留下下一堂課的情境焦點與風險學員註記。",
                    ]
                ),
                "estimated_minutes": 25,
                "required": True,
            },
            {
                "slug": "ai-runtime-collaboration",
                "title": "AI Runtime 協作流程",
                "summary": "理解 MCP / AI 教案、學習數據與真人教師的交接方式。",
                "content": "\n".join(
                    [
                        "1. 開課前先讀 AI 教案草稿與市場提煉出的黃金教學框架。",
                        "2. 課中要延續 AI 標記出的弱點，安排情境對話與 Shadowing 修正。",
                        "3. 課後將口說流暢度、作業風險與下次建議同步回學務報表。",
                        "4. 當 AI 建議與真人觀察不同時，要在紀錄裡明確標註原因。",
                    ]
                ),
                "estimated_minutes": 15,
                "required": True,
            },
        ],
        "questions": [
            {
                "section_slug": "platform-ops",
                "prompt": "老師登入平台後的第一件事應該是什麼？",
                "options": [
                    "A. 直接開始講解文法",
                    "B. 查看 AI 同步的學員實戰數據與弱點摘要",
                    "C. 先寄招生簡訊給潛在名單",
                ],
                "correct_option": "B",
                "explanation": "平台要求老師先理解學員最新學習狀態，再決定教學節奏。",
                "sort_order": 1,
            },
            {
                "section_slug": "platform-ops",
                "prompt": "學員口說流暢度追蹤卡最晚應在何時提交？",
                "options": [
                    "A. 下課後 10 分鐘內",
                    "B. 隔天中午前",
                    "C. 每週統一一次提交",
                ],
                "correct_option": "A",
                "explanation": "課後 10 分鐘內回填，才能讓學務與 AI 報表保持即時。",
                "sort_order": 2,
            },
            {
                "section_slug": "golden-speaking-sop",
                "prompt": "平台要求每堂真人課至少保留多少 Shadowing 時間？",
                "options": [
                    "A. 5 分鐘",
                    "B. 10 分鐘",
                    "C. 15 分鐘",
                ],
                "correct_option": "C",
                "explanation": "15 分鐘 Shadowing 是平台的最低標準，不能省略。",
                "sort_order": 1,
            },
            {
                "section_slug": "golden-speaking-sop",
                "prompt": "最符合平台黃金口說教學法的開場方式是？",
                "options": [
                    "A. 先連續講 30 分鐘文法",
                    "B. 先用情境任務引導學員開口，再即時修正",
                    "C. 先讓學員默寫單字 20 分鐘",
                ],
                "correct_option": "B",
                "explanation": "平台主張以情境引導開口，不做單向灌輸。",
                "sort_order": 2,
            },
            {
                "section_slug": "ai-runtime-collaboration",
                "prompt": "老師在課前面對 AI 草稿時，最正確的做法是什麼？",
                "options": [
                    "A. 完全忽略 AI 草稿",
                    "B. 先閱讀 AI 教案與弱點摘要，再做真人調整",
                    "C. 把 AI 草稿直接貼給學員當講義",
                ],
                "correct_option": "B",
                "explanation": "AI 草稿是起點，老師需在上課前做專業調整。",
                "sort_order": 1,
            },
            {
                "section_slug": "ai-runtime-collaboration",
                "prompt": "如果老師觀察到的弱點與 AI 建議不同，應如何處理？",
                "options": [
                    "A. 什麼都不記錄，照自己習慣上課",
                    "B. 在課後紀錄中說明差異與調整原因",
                    "C. 直接停用整個平台",
                ],
                "correct_option": "B",
                "explanation": "平台需要把真人判斷回寫，才能持續優化教學模型。",
                "sort_order": 2,
            },
        ],
    }
