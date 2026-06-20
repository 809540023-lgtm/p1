from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_LANG_ALIASES = {
    "": "zh-Hant",
    "zh-hant": "zh-Hant",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "hant": "zh-Hant",
    "tw": "zh-Hant",
    "traditional": "zh-Hant",
    "zh-hans": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "hans": "zh-Hans",
    "cn": "zh-Hans",
    "simplified": "zh-Hans",
}

_SCHOOL_PLATFORM_URL_PATTERN = re.compile(
    r'(?P<attr>(?:href|action))=(?P<quote>["\'])(?P<url>/school-platform[^"\']*)(?P=quote)'
)

_FALLBACK_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("試聽預約已送出", "试听预约成功"),
    ("試聽預約成功", "试听预约成功"),
    ("免費試聽預約", "免费试听预约"),
    ("課程總覽", "课程总览"),
    ("課程詳情", "课程详情"),
    ("正式報名", "正式报名"),
    ("學員中心總覽", "学员中心总览"),
    ("學習進度中心", "学习进度中心"),
    ("學習進度總覽", "学习进度总览"),
    ("整體學習評估", "整体学习评估"),
    ("平台開發進度總覽", "平台开发进度总览"),
    ("最近開發紀錄", "最近开发纪录"),
    ("完整營運平台架構", "完整营运平台架构"),
    ("系統與資料層狀態", "系统与资料层状态"),
    ("目前 backend", "当前 backend"),
    ("下一步", "下一步"),
    ("目前 row-level 覆蓋表", "当前 row-level 覆盖表"),
    ("跑 smoke test", "跑 smoke test"),
    ("Recommended Commands", "Recommended Commands"),
    ("PostgreSQL 一鍵 rehearsal", "PostgreSQL 一键 rehearsal"),
    ("部署 smoke test", "部署 smoke test"),
    ("PostgreSQL row-level write probe", "PostgreSQL row-level write probe"),
    ("一鍵 rehearsal", "一键 rehearsal"),
    ("驗證部署 smoke test", "验证部署 smoke test"),
    ("營運後台總覽", "营运后台总览"),
    ("招生名單管理", "招生名单管理"),
    ("班級管理", "班级管理"),
    ("課程管理", "课程管理"),
    ("教師管理", "教师管理"),
    ("教務管理", "教务管理"),
    ("教師工作台", "教师工作台"),
    ("招生顧問工作台", "招生顾问工作台"),
    ("員工績效中心", "员工绩效中心"),
    ("財務中心", "财务中心"),
    ("排課中心", "排课中心"),
    ("AI 教案草稿中心", "AI 教案草稿中心"),
    ("報表中心", "报表中心"),
    ("應徵者詳情", "应征者详情"),
    ("面試紀錄與評分", "面试纪录与评分"),
    ("面試評分與結論", "面试评分与结论"),
    ("更新案件進度", "更新案件进度"),
    ("儲存案件進度", "保存案件进度"),
    ("儲存面試結論", "保存面试结论"),
    ("面試回饋", "面试回馈"),
    ("案件階段", "案件阶段"),
    ("面試流程建議", "面试流程建议"),
    ("錄取通知", "录取通知"),
    ("AI 練習區", "AI 练习区"),
    ("AI 助理中心", "AI 助理中心"),
    ("子帳號中心", "子账号中心"),
    ("建立新子帳號", "建立新子账号"),
    ("建立子帳號", "建立子账号"),
    ("主帳號", "主账号"),
    ("子帳號", "子账号"),
    ("帳號總數", "账号总数"),
    ("啟用中", "启用中"),
    ("停用", "停用"),
    ("目前帳號清單", "目前账号清单"),
    ("主帳號與子帳號管理", "主账号与子账号管理"),
    ("AI Provider 狀態", "AI Provider 状态"),
    ("服務可用", "服务可用"),
    ("外部模型就緒", "外部模型就绪"),
    ("目前供應商", "当前供应商"),
    ("最近 provider 錯誤", "最近 provider 错误"),
    ("查看 AI status JSON", "查看 AI status JSON"),
    ("學員管理", "学员管理"),
    ("學員名單", "学员名单"),
    ("學員檔案", "学员档案"),
    ("查看學員檔案", "查看学员档案"),
    ("查看學員詳情 JSON", "查看学员详情 JSON"),
    ("查看學員 JSON", "查看学员 JSON"),
    ("學員總數", "学员总数"),
    ("進行中學員", "进行中学员"),
    ("待付款學員", "待付款学员"),
    ("待處理通知", "待处理通知"),
    ("回學員管理", "回学员管理"),
    ("目前課程", "目前课程"),
    ("最近歷程", "最近历程"),
    ("訊息中心", "讯息中心"),
    ("發送訊息", "发送讯息"),
    ("最近通知紀錄", "最近通知纪录"),
    ("查看訊息總覽 JSON", "查看讯息总览 JSON"),
    ("廣播訊息", "广播讯息"),
    ("通知總數", "通知总数"),
    ("待送出", "待发送"),
    ("已讀", "已读"),
    ("站內通知", "站内通知"),
    ("對象", "对象"),
    ("單一學員", "单一学员"),
    ("進行中學員", "进行中学员"),
    ("全部學員", "全部学员"),
    ("管理團隊", "管理团队"),
    ("指定 Email（單一學員時使用）", "指定 Email（单一学员时使用）"),
    ("標題", "标题"),
    ("內容", "内容"),
    ("回營運總覽", "回营运总览"),
    ("主管工作台", "主管工作台"),
    ("打開主管工作台", "打开主管工作台"),
    ("查看主管 JSON", "查看主管 JSON"),
    ("核心摘要", "核心摘要"),
    ("營運警示", "营运警示"),
    ("熱度最高名單", "热度最高名单"),
    ("高風險學員", "高风险学员"),
    ("班級容量觀察", "班级容量观察"),
    ("AI 模組使用", "AI 模组使用"),
    ("本週建議", "本周建议"),
    ("進行中班級", "进行中班级"),
    ("逾期跟進", "逾期跟进"),
    ("待評分", "待评分"),
    ("待處理客服", "待处理客服"),
    ("已收營收", "已收营收"),
    ("待收營收", "待收营收"),
    ("開放職缺", "开放职缺"),
    ("面試安排", "面试安排"),
    ("前往報表中心", "前往报表中心"),
    ("班級教學詳情", "班级教学详情"),
    ("查看班級詳情", "查看班级详情"),
    ("查看班級 JSON", "查看班级 JSON"),
    ("Row-level Mutation Coverage", "Row-level Mutation Coverage"),
    ("快速點名", "快速点名"),
    ("送出點名", "提交点名"),
    ("班級執行摘要", "班级执行摘要"),
    ("待批改作業", "待批改作业"),
    ("待批改測驗", "待批改测验"),
    ("出席狀態", "出席状态"),
    ("送出作業評分", "提交作业评分"),
    ("送出測驗評分", "提交测验评分"),
    ("最近出缺勤", "最近出缺勤"),
    ("高風險", "高风险"),
    ("中風險", "中风险"),
    ("待補作業", "待补作业"),
    ("待補測驗", "待补测验"),
    ("出缺勤紀錄", "出缺勤纪录"),
    ("顧問案件詳情", "顾问案件详情"),
    ("打開案件詳情", "打开案件详情"),
    ("回顧問工作台", "回顾问工作台"),
    ("查看案件 JSON", "查看案件 JSON"),
    ("查看 AI 草稿 JSON", "查看 AI 草稿 JSON"),
    ("AI 跟進草稿", "AI 跟进草稿"),
    ("建議渠道", "建议渠道"),
    ("建議下一步", "建议下一步"),
    ("LINE 話術草稿", "LINE 话术草稿"),
    ("新增跟進", "新增跟进"),
    ("招聘管理", "招聘管理"),
    ("進行中 onboarding", "进行中 onboarding"),
    ("試用期追蹤", "试用期追踪"),
    ("到職 / 試用追蹤", "到职 / 试用追踪"),
    ("更新 onboarding / probation", "更新 onboarding / probation"),
    ("儲存 onboarding / probation", "保存 onboarding / probation"),
    ("通知中心", "通知中心"),
    ("客服需求中心", "客服需求中心"),
    ("客服收件箱", "客服收件箱"),
    ("客服案件詳情", "客服案件详情"),
    ("我的課表", "我的课表"),
    ("我的歷程", "我的历程"),
    ("作業中心", "作业中心"),
    ("出缺勤", "出缺勤"),
    ("測驗中心", "测验中心"),
    ("加入 AI 日語補習班團隊", "加入 AI 日语补习班团队"),
    ("查看課程詳情", "查看课程详情"),
    ("查看學員進度", "查看学员进度"),
    ("查看教師工作台", "查看教师工作台"),
    ("查看顧問工作台", "查看顾问工作台"),
    ("查看招生名單", "查看招生名单"),
    ("查看財務 JSON", "查看财务 JSON"),
    ("查看排課 JSON", "查看排课 JSON"),
    ("打開 AI 教案中心", "打开 AI 教案中心"),
    ("查看應徵者詳情", "查看应征者详情"),
    ("高意向名單", "高意向名单"),
    ("待跟進隊列", "待跟进队列"),
    ("最近更新", "最近更新"),
    ("教師排課負載", "教师排课负载"),
    ("排課衝堂檢查", "排课冲堂检查"),
    ("班級時段總覽", "班级时段总览"),
    ("教學目標", "教学目标"),
    ("建議面試題", "建议面试题"),
    ("關鍵句型", "关键句型"),
    ("練習提示", "练习提示"),
    ("自我檢查", "自我检查"),
    ("語言切換", "语言切换"),
    ("繁體中文", "繁体中文"),
    ("簡體中文", "简体中文"),
    ("平台入口總覽", "平台入口总览"),
    ("今日可營運", "今日可营运"),
    ("今天可直接營運的狀態", "今天可直接营运的状态"),
    ("今日可否直接營運", "今日可否直接营运"),
    ("直接操作入口", "直接操作入口"),
    ("本機示範帳號", "本机示范账号"),
    ("Gmail SMTP 最短設定", "Gmail SMTP 最短设定"),
    ("LINE 外發需要什麼", "LINE 外发需要什么"),
    ("常用模板", "常用模板"),
    ("setup guide", "setup guide"),
    ("如果你要先讓", "如果你要先让"),
    ("開始寄真信", "开始寄真信"),
    ("示範帳號", "示范账号"),
    ("工作入口", "工作入口"),
    ("正式對外前還差", "正式对外前还差"),
    ("核心模組狀態", "核心模组状态"),
    ("這份狀態是看今天能不能直接進站操作，不把 PostgreSQL、Stripe、真實 Email 憑證混成同一件事。", "这份状态是看今天能不能直接进站操作，不把 PostgreSQL、Stripe、真实 Email 凭证混成同一件事。"),
    ("角色入口", "角色入口"),
    ("對外成長入口", "对外成长入口"),
    ("學習與教學入口", "学习与教学入口"),
    ("營運與管理入口", "营运与管理入口"),
    ("系統與開發入口", "系统与开发入口"),
    ("課程示範入口", "课程示范入口"),
    ("學員中心", "学员中心"),
    ("如果你現在不是要看全部頁面，而是想直接進入某一種工作流，先從這裡點最不會迷路。", "如果你现在不是要看全部页面，而是想直接进入某一种工作流，先从这里点最不容易迷路。"),
    ("這個首頁不是單一宣傳頁，而是整個 AI 日語補習班平台的入口地圖。招商、課程、學員、教師、營運、報表與系統檢查都集中在這一頁。", "这个首页不是单一宣传页，而是整个 AI 日语补习班平台的入口地图。招商、课程、学员、教师、营运、报表与系统检查都集中在这一页。"),
)


def normalize_ui_lang(value: str | None) -> str:
    key = (value or "").strip().lower()
    return _LANG_ALIASES.get(key, "zh-Hant")


@lru_cache(maxsize=1)
def _opencc_converter():
    try:
        from opencc import OpenCC
    except Exception:
        return None
    return OpenCC("t2s")


def _fallback_localize(text: str) -> str:
    localized = text
    for source, target in _FALLBACK_REPLACEMENTS:
        localized = localized.replace(source, target)
    return localized


def append_lang_to_url(url: str, lang: str) -> str:
    if not url:
        return url
    normalized_lang = normalize_ui_lang(lang)
    parsed = urlparse(url)
    if not parsed.path.startswith("/school-platform"):
        return url
    query_items = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "lang"]
    if normalized_lang == "zh-Hans":
        query_items.append(("lang", "zh-Hans"))
    rebuilt_query = urlencode(query_items)
    return urlunparse(parsed._replace(query=rebuilt_query))


def localize_school_platform_html(html_text: str, lang: str) -> str:
    normalized_lang = normalize_ui_lang(lang)
    if normalized_lang != "zh-Hans":
        return html_text

    localized = _SCHOOL_PLATFORM_URL_PATTERN.sub(
        lambda match: (
            f"{match.group('attr')}={match.group('quote')}"
            f"{append_lang_to_url(match.group('url'), normalized_lang)}"
            f"{match.group('quote')}"
        ),
        html_text,
    )
    localized = localized.replace('lang="zh-Hant"', 'lang="zh-Hans"')
    converter = _opencc_converter()
    if converter is None:
        return _fallback_localize(localized)
    return converter.convert(localized)
