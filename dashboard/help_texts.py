# SPDX-License-Identifier: AGPL-3.0-or-later
"""控制台每个设置旁边「?」卡片的说明文字 —— 全部集中在这一张表里。

为什么集中放：以后做网页多语言（#1792）时只翻这一个文件；HTML 里只写 `data-help="键"`。
计划和来源见 docs/settings-help-plan.md。

每条的字段：
  what  是什么（必填）
  up    打开 / 调大会怎样
  down  关闭 / 调小会怎样
  when  什么时候生效（必填，用下面几个常量，用户最分不清的就是这个）
  warn  有坑的再写（可选）
  kind  "switch"（开关：显示「打开 / 关闭」）| "num"（数字：显示「调大 / 调小」）| "info"（只有说明）
        前端按 kind 决定 up / down 两行的小标题。
"""

NOW = "立即生效"
NOW_KEEP = "立即生效，重启 / 断电后保持"
RESTART = "保存后要重启服务才生效（原生：./stop.sh && ./start.sh；Docker：docker compose restart）"
RESTART_DL = "保存后要重启下载器才生效"
RESTART_UZ = "保存后要重启解压器才生效"
RESTART_MV = "保存后要重启搬运器才生效"
RESTART_CTL = "保存后要重启 control 服务才生效（docker compose restart control）"

HELP: dict[str, dict[str, str]] = {
    # ── 暂停开关 ────────────────────────────────────────────────────────────
    "pause_global": {
        "kind": "switch",
        "what": "暂停普通频道的新消息下载。",
        "up": "普通频道发了新文件也不下；已经在下载、在排队的不受影响，照样下完。",
        "down": "恢复收取普通频道的新文件。",
        "when": NOW_KEEP,
        "warn": "「例外频道」和「收藏」不归它管，各有各的开关。",
    },
    "pause_exempt": {
        "kind": "switch",
        "what": "暂停「例外频道」的新消息下载。",
        "up": "例外频道也停收。",
        "down": "例外频道照常收，哪怕全局暂停是开着的。",
        "when": NOW_KEEP,
    },
    "pause_saved": {
        "kind": "switch",
        "what": "暂停你自己的「收藏（Saved Messages）」：往收藏里转发或上传的文件会自动下载，这个开关管它。",
        "up": "收藏里新来的文件不下载。往收藏发 t.me 链接、发「状态」照常处理（那是你主动要的）。",
        "down": "收藏里新来的文件照常下载。",
        "when": NOW_KEEP,
    },
    "pause_mover": {
        "kind": "switch",
        "what": "暂停搬运：下载完的压缩包从下载目录搬到解压目录这一步。",
        "up": "压缩包堆在下载目录里，不搬也不解压；下载不受影响。",
        "down": "继续搬，积压的会依次处理。",
        "when": NOW_KEEP,
    },
    "pause_unzipper": {
        "kind": "switch",
        "what": "暂停自动解压。",
        "up": "搬过来的压缩包放着不解；搬运和下载不受影响。",
        "down": "继续解压，积压的会依次处理。",
        "when": NOW_KEEP,
    },
    "exempt_channel": {
        "kind": "info",
        "what": "把某个频道设成「例外」：它只受「例外暂停」管，全局暂停时照样下载。适合少数一定要实时收的频道。",
        "when": NOW,
    },

    # ── 页面 / 服务 ─────────────────────────────────────────────────────────
    "branding": {
        "kind": "info",
        "what": "左上角和浏览器标签页上显示的名字。留空 = 用登录的 Telegram 账号名；也可以隐藏，只显示「TGhelper」。",
        "when": NOW,
    },
    "autostart": {
        "kind": "switch",
        "what": "电脑开机后自动把下载、搬运、解压、控制台都启动起来。只有原生部署（不用 Docker）才在这里开关。",
        "up": "开机就开始干活，断电来电后不用人管。",
        "down": "开机后要自己运行 ./start.sh。",
        "when": "下次开机生效",
        "warn": "Docker 部署由 Docker 自己负责（容器设了 restart: unless-stopped），这里只显示状态。",
    },
    "services": {
        "kind": "info",
        "what": "单独启动 / 停止 / 重启下载、搬运、解压三个服务。只有 Docker 部署才有。",
        "when": NOW,
        "warn": "你手动停掉的服务会一直停着，「卡死自动重启」也不会去拉它，直到你在这里点「启动」。",
    },
    "AUTOHEAL": {
        "kind": "switch",
        "what": "服务卡死（进程还活着、但不响应）时自动重启它。只有 Docker 部署才有。",
        "up": "卡死后 1 分钟左右自动重启；同一个服务 10 分钟内不重复重启，1 小时超过 3 次就停手并发通知。",
        "down": "卡死了只能你自己重启。",
        "when": RESTART_CTL,
    },

    # ── 数据目录 ────────────────────────────────────────────────────────────
    "DATA_ROOT": {
        "kind": "info",
        "what": "数据总目录。只填这一个就行：下面会自动建 telegramDMZ/download（下载）、move（待解压）、unzip（解压结果）三个子目录。",
        "when": RESTART,
        "warn": "Docker 部署这里只读，要改宿主机 .env 的 HOST_DATA_ROOT 再 docker compose up -d。",
    },
    "DOWNLOAD_DIR": {
        "kind": "info",
        "what": "下载的文件放哪。留空 = 用数据总目录下的 download。",
        "when": RESTART,
        "warn": "三个目录不能相同，也不能一个套在另一个里面，否则会被当成重复文件、误触发解压。",
    },
    "WATCH_PATH": {
        "kind": "info",
        "what": "压缩包下载完搬到哪；解压器盯着这个目录，有新压缩包就解。留空 = 数据总目录下的 move。",
        "when": RESTART,
        "warn": "三个目录不能相同，也不能互相包含。",
    },
    "OUTPUT_PATH": {
        "kind": "info",
        "what": "解压出来的东西放哪。留空 = 数据总目录下的 unzip。",
        "when": RESTART,
        "warn": "三个目录不能相同，也不能互相包含。",
    },

    # ── 性能与行为 ──────────────────────────────────────────────────────────
    "MAX_TOTAL_CONNECTIONS": {
        "kind": "num",
        "what": "同时连 Telegram 下载的连接总数（所有任务加起来）。大文件一个任务会开好几条。",
        "up": "并发多，带宽够时更快；但更容易被 Telegram 限流。",
        "down": "稳，但慢。",
        "when": NOW + "（保存时同步给下载器）",
        "warn": "速度上不去时先看「正在下载」有几个任务，不一定是它不够：文件中等大小时 8 个任务就能用满 16 条。",
    },
    "MAX_CONCURRENT_TASKS": {
        "kind": "num",
        "what": "同时解压几个压缩包。",
        "up": "积压的解得快，但吃 CPU 和磁盘；硬盘慢时反而互相拖。",
        "down": "一个一个来，不抢资源。",
        "when": RESTART_UZ,
    },
    "MOVER_MAX_CONCURRENT": {
        "kind": "num",
        "what": "同时搬运几个文件。同一块盘里搬是改名，几乎不花时间；跨盘才是真的复制。",
        "up": "跨盘搬运时多个一起复制。",
        "down": "跨盘时一个一个复制，不抢磁盘。",
        "when": RESTART_MV,
    },
    "DOWNLOAD_TIMEOUT": {
        "kind": "num",
        "what": "一个下载连续多少秒没有任何进度，就判定卡死、取消后重来（已下的分块会保留，接着下）。",
        "up": "网络差时不容易被误判卡死，但真卡死要等更久才发现。",
        "down": "卡死发现得快，但网络抖一下就可能被误杀。",
        "when": RESTART_DL,
        "warn": "不能低于 Telegram 限流自动等待时间的 2 倍（默认 120 秒）。设成 60 这种值，大文件会被反复误杀、永远下不完。",
    },
    "AUTO_MOVE": {
        "kind": "switch",
        "what": "压缩包下载完自动交给搬运 → 解压。普通文件（视频、图片）不经过这一步。",
        "up": "下完自动搬走、自动解压。",
        "down": "压缩包留在下载目录，不会自动解压。",
        "when": RESTART_DL,
    },
    "RESTART_MODE": {
        "kind": "info",
        "what": "重启或断电来电后，各个暂停开关怎么办。「恢复上次状态」= 回到关机前的样子；「一律暂停」= 先全部停着，等你来点。",
        "when": "下次启动生效",
        "warn": "离线期间积压了很多、不想一开机就全速下载时，临时改成「一律暂停」。",
    },
    "LOG_LEVEL": {
        "kind": "info",
        "what": "日志写多细。平时 INFO；排查问题时临时开 DEBUG（日志会多很多）。",
        "when": RESTART,
    },
    "DOWNLOAD_START_INTERVAL": {
        "kind": "num",
        "what": "两个下载开始之间至少隔几秒，防止短时间内大量请求被 Telegram 判成异常（防封号）。0 = 不限制。",
        "up": "更不像机器人，但积压多时整体变慢。",
        "down": "开工快。",
        "when": RESTART_DL,
    },
    "DOWNLOAD_START_JITTER": {
        "kind": "num",
        "what": "在上面的间隔上再随机多等 0 到这么多秒，让节奏不那么规律。0 = 不随机。",
        "up": "间隔更随机。",
        "down": "间隔固定。",
        "when": RESTART_DL,
    },

    # ── 高级：下载调度 ──────────────────────────────────────────────────────
    "RECOVER_WORKERS": {
        "kind": "num",
        "what": "下载器重启后，同时恢复几个没下完的任务。",
        "up": "恢复得快，但刚启动那阵子会很卡、页面反应慢。",
        "down": "启动平稳，恢复慢。",
        "when": RESTART_DL,
        "warn": "不能超过总连接数。",
    },
    "STALLED_RETRY_INTERVAL": {
        "kind": "num",
        "what": "「搁置」的任务（下失败了、没人管的）每隔多少秒自动重试一轮。最小 60 秒。",
        "up": "重试得少，不占正常下载的名额。",
        "down": "失败的任务更快被捞回来，但太勤会挤掉正常下载。",
        "when": RESTART_DL,
    },
    "STALLED_RETRY_BATCH": {
        "kind": "num",
        "what": "每轮最多重试几个搁置任务。",
        "up": "一轮捞回更多。",
        "down": "对正常下载影响小。",
        "when": RESTART_DL,
    },
    "HISTORY_CONN_FRACTION": {
        "kind": "num",
        "what": "下载历史消息最多占总连接数的多少（0.1–0.9），剩下的留给新消息。",
        "up": "历史下得快，但新消息可能要排队。",
        "down": "新消息优先，历史慢慢下。",
        "when": RESTART_DL,
    },
    "HISTORY_TAKEOUT": {
        "kind": "switch",
        "what": "下载历史消息时，翻消息列表这一步改用 Telegram 的「数据导出（takeout）」通道。实测翻得快 4 倍多、几乎不被限流。只管翻列表，文件本身照旧走普通下载。",
        "up": "大频道扫历史快很多，少被限流卡住。",
        "down": "默认就是关，和以前完全一样。",
        "when": RESTART_DL,
        "warn": "takeout 申请不到或用到一半失效时，会自动退回普通方式接着扫，不丢不重，日志里记一行「[takeout] …退回普通会话」。",
    },
    "SMALL_FILE_THRESHOLD_MB": {
        "kind": "num",
        "what": "多大以下算「小文件」（MB）。小文件可以用下面预留的专用连接，不会被大文件堵住。",
        "up": "更多文件能走专用连接。",
        "down": "只有很小的文件能走专用连接。",
        "when": RESTART_DL,
    },
    "SMALL_FILE_RESERVED_CONNECTIONS": {
        "kind": "num",
        "what": "给小文件留几条专用连接。大文件用不了这几条。",
        "up": "小文件随到随下，但大文件可用的连接变少。",
        "down": "大文件更快；一堆大文件在下时，小文件要排队。0 = 不预留。",
        "when": RESTART_DL,
        "warn": "必须小于总连接数。",
    },

    # ── 解压 ────────────────────────────────────────────────────────────────
    "UNZIPPER_7Z_TIMEOUT": {
        "kind": "num",
        "what": "解一个压缩包最多等多少秒，超过算卡死。留空 = 按大小自动算（至少 10 分钟，按 5 MB/s 估）。",
        "up": "超大包、慢硬盘不容易被误判卡死。",
        "down": "真卡死能早点发现；但填太小会把正常的大包也判死。",
        "when": RESTART_UZ,
        "warn": "填了就所有包都用这个数，不再按大小算。拿不准就留空。",
    },
    "UNZIPPER_SCAN_INTERVAL": {
        "kind": "num",
        "what": "解压器每隔多少秒补扫一次目录。平时靠文件监听，补扫是为了捡漏（网络盘上监听可能不灵）。最小 2 秒。",
        "up": "省一点资源；漏掉的包要晚一点才被发现。",
        "down": "捡漏更及时。",
        "when": RESTART_UZ,
    },

    # ── 记录保留 ────────────────────────────────────────────────────────────
    "MAX_HISTORY": {
        "kind": "num",
        "what": "下载完成记录最多留多少条（页面上的「最近完成」、去重都看它）。",
        "up": "能查得更久；记录文件变大，页面变慢。",
        "down": "省空间、页面快；太旧的记录会被删掉。",
        "when": RESTART_DL,
    },
    "MOVER_MAX_HISTORY": {
        "kind": "num",
        "what": "搬运记录最多留多少条。",
        "up": "能查得更久，占空间。",
        "down": "省空间。",
        "when": RESTART_MV,
    },
    "HISTORY_JOB_KEEP_DAYS": {
        "kind": "num",
        "what": "做完的「历史下载」任务记录保留几天。",
        "up": "能查得更久。",
        "down": "列表更干净。",
        "when": RESTART_DL,
    },
    "LOG_KEEP_DAYS": {
        "kind": "num",
        "what": "日志文件保留几天，过期的自动删。",
        "up": "能往回查得更久，占磁盘。",
        "down": "省磁盘。",
        "when": RESTART,
    },

    # ── 安全 ────────────────────────────────────────────────────────────────
    "MOVE_ALLOWED_ROOTS": {
        "kind": "info",
        "what": "允许搬运器把文件搬到哪些地方（数据目录之外的）。一行一个绝对路径。数据目录本身一直允许，不用写。",
        "when": RESTART_MV,
        "warn": "这是安全护栏：不在名单里的地方一律拒绝搬，防止被人通过接口把文件写到系统目录。只加你确定要用的目录，别写 / 这种大范围的。",
    },
    "notify": {
        "kind": "info",
        "what": "服务崩溃、磁盘快满、自动重启失败时给你发 Telegram 消息。聊天 ID 是你自己（或某个群）的数字 ID，不填就不发。机器人 Token 在 @BotFather 那里建，可以不填：不填时只有下载器能用登录的账号代发，搬运 / 解压 / control 出事就发不出来。",
        "when": RESTART + "；「发一条测试」用的是框里的值，不用先保存",
        "warn": "Token 等于机器人的钥匙：这里只写不读，保存后页面上只显示「已设置」。",
    },
    "API_KEY": {
        "kind": "info",
        "what": "访问控制台和各个接口要输的密码。只有本机能访问时可以不设；同一个局域网 / 公网能访问时一定要设。",
        "when": "只能在 .env 里改，改完重启",
        "warn": "故意不放在网页上改：改错了会把自己锁在外面。",
    },
    "passwords": {
        "kind": "info",
        "what": "解压带密码的压缩包时，按列表顺序一个个试。",
        "when": NOW,
        "warn": "常用的放前面，试得快。",
    },
}


# ── 英文（#1792 全局双语底座做好前先放这里，到时并进语言表）───────────────────
# 新加的设置项从一开始就写中英两份。label = 设置页上的名字。
RESTART_DL_EN = "Takes effect after the downloader restarts"

HELP_EN: dict[str, dict[str, str]] = {
    "HISTORY_TAKEOUT": {
        "kind": "switch",
        "label": "Use takeout for history scans",
        "what": "When downloading a chat's history, list its messages through Telegram's data-export (takeout) channel. "
                "In tests this was over 4x faster and almost never rate-limited. Only the message listing uses it; "
                "files are still downloaded the normal way.",
        "up": "Scanning large chats is much faster and rarely stalls on rate limits.",
        "down": "Off by default; behaves exactly as before.",
        "when": RESTART_DL_EN,
        "warn": "If a takeout session can't be opened, or stops working mid-scan, scanning automatically continues "
                "the normal way from where it stopped (nothing skipped or repeated), and one line is written to the log "
                "(\"[takeout] … 退回普通会话\").",
    },
}

LABEL_ZH = {
    "HISTORY_TAKEOUT": "扫历史用 takeout 通道",
}


def missing_keys(keys) -> list[str]:
    """给测试用：页面上引用了、表里却没有的键。"""
    return sorted(k for k in set(keys) if k not in HELP)
