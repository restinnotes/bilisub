# BiliSub

让没有字幕的 B 站视频也能显示 `AI字幕`。

它由两部分组成：

- `extension/`：Chrome 扩展，负责在 B 站播放器里显示 `AI字幕` 按钮和字幕
- `server/`：本地服务，负责拉音频、调用 Groq / 本地 whisper、缓存字幕

## 最简单用法

### 第一次使用

1. 双击 [setup-bilisub.cmd](C:/Users/zuoyi/Desktop/Dev/bilisub/setup-bilisub.cmd)
2. 等它自动安装依赖并启动本地服务
3. 打开 `chrome://extensions`
4. 开启右上角“开发者模式”
5. 点击“加载已解压的扩展程序”
6. 选择目录 [extension](C:/Users/zuoyi/Desktop/Dev/bilisub/extension)

做完一次之后，后面一般就不用再重复装扩展了。

### 以后日常使用

- 直接双击 [start-bilisub.cmd](C:/Users/zuoyi/Desktop/Dev/bilisub/start-bilisub.cmd)
- 打开任意 B 站视频
- 在播放器里点击 `AI字幕`

## 需要什么环境

- Windows
- Python 3.10+
- `ffmpeg`
- Chrome

如果缺少 Python 或 ffmpeg，`setup-bilisub.cmd` 会尽量提示你。

## 常见问题

### 1. 打开视频后没有字幕

先确认两件事：

- 本地服务是否在运行：打开 [http://127.0.0.1:8765/health](http://127.0.0.1:8765/health)
- 播放器里的 `AI字幕` 按钮是否已经打开

### 2. 为什么不是默认自动显示

现在设计为默认关闭，避免和 B 站原生字幕混淆。  
需要时手动点播放器里的 `AI字幕` 开关。

### 3. 字幕缓存会一直堆积吗

不会。现在会自动清理：

- 超过 30 天的缓存会删除
- 总缓存超过 1GB 时，会从最老的开始删

缓存目录在 [server/cache/subtitles](C:/Users/zuoyi/Desktop/Dev/bilisub/server/cache/subtitles)

## 重要文件

- 一键安装： [setup-bilisub.cmd](C:/Users/zuoyi/Desktop/Dev/bilisub/setup-bilisub.cmd)
- 日常启动： [start-bilisub.cmd](C:/Users/zuoyi/Desktop/Dev/bilisub/start-bilisub.cmd)
- 后台服务启动脚本： [start-bilisub-server.ps1](C:/Users/zuoyi/Desktop/Dev/bilisub/start-bilisub-server.ps1)
- Chrome 扩展目录： [extension](C:/Users/zuoyi/Desktop/Dev/bilisub/extension)
