// ==UserScript==
// @name         Live Stream Chat AI Agent
// @name:zh-CN   直播聊天室AI智能代理
// @version      0.8
// @description  An AI script for automatically sending chat messages and interacting with the streamer on Bilibili live streams. Records audio, chat, and screenshots, sends to backend for AI processing, and posts responses automatically.
// @description:zh-CN  一个基于 AI 的脚本，用于在 Bilibili 直播中自动发送弹幕消息并与主播互动。录制音频、弹幕、直播间画面，发送到后端进行 AI 处理，并自动发布 AI 生成的聊天内容。
// @description:zh-TW  一個基於人工智慧的腳本，用於在 Bilibili 直播中自動發送聊天室訊息並與主播互動。錄製音訊、彈幕和直播畫面，傳送到後端進行 AI 處理，並自動發佈聊天室內容。
// @description:zh-HK  一個基於人工智能的腳本，用於在 Bilibili 直播中自動發送聊天室訊息並與主播互動。錄製音訊、彈幕及直播畫面，傳送至後台進行 AI 分析處理，並自動發佈聊天室內容。
// @author       bOc
// @match        https://live.bilibili.com/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    // --- 常量定义 ---
    const API_ENDPOINT = 'https://your_server_address:8181/upload'; // 后端 API 地址
    const RECORDING_INTERVAL_MS = 30000; // 30 秒 - 录制分块时长
    const MAX_CHAT_LENGTH = 20; // 每条弹幕消息分段的最大长度
    const CHAT_SEND_DELAY_MIN_MS = 3000; // 发送弹幕消息之间的最小延迟（毫秒）
    const CHAT_SEND_DELAY_MAX_MS = 6000; // 发送弹幕消息之间的最大延迟（毫秒）
    const SCREENSHOT_WIDTH = 1280; // 期望的截图宽度
    const SCREENSHOT_HEIGHT = 720; // 期望的截图高度
    const SCREENSHOT_QUALITY = 0.9; // 截图 JPEG 质量 (0.0 到 1.0)

    // --- 状态变量 ---
    let audioContext; // AudioContext 实例
    let destination; // 用于录制的 MediaStreamAudioDestinationNode
    let mediaElementSource; // 来自视频元素的 MediaElementAudioSourceNode
    let gainNode; // 用于控制音量/静音的 GainNode

    let mediaRecorder1; // 第一个 MediaRecorder 实例
    let mediaRecorder2; // 第二个 MediaRecorder 实例（用于无缝录制切换）
    let recorder1Timeout; // 录制器 1 的 Timeout ID
    let recorder2Timeout; // 录制器 2 的 Timeout ID
    let isRecorder1Active = false; // 标记录制器 1 是否活动 (更明确的命名)
    let isRecorder2Active = false; // 标记录制器 2 是否活动 (更明确的命名)
    let isAgentRunning = false; // 标记整个代理是否处于用户启动的运行状态
    let isSending = false; // 标记当前是否正在向后端发送数据
    let chunks1 = []; // 录制器 1 的音频数据块
    let chunks2 = []; // 录制器 2 的音频数据块
    let accumulatedChunks = []; // 如果上一个发送仍在进行中，用于存储音频块
    let isAccumulating = false; // 标记是否正在累积音频块

    let recordingStartTimestamp = 0; // 当前录制块开始的时间戳
    let recordingEndTimestamp = 0; // 当前录制块结束的时间戳

    let chatQueue = []; // 用于存放待发送弹幕消息的队列

    // --- UI 和控制变量 ---
    let isMainSwitchOn = false; // 主控制开关状态
    let isChatPermissionGranted = false; // 发送弹幕权限状态
    let isMuted = false; // 直播音频静音状态
    let volumeSlider; // 音量滑块元素的引用
    let runButton; // 运行/停止按钮元素的引用 (改名)
    let panel; // 主 UI 面板的引用

    // --- 初始化 ---
    const roomId = getRoomId();
    if (!roomId) {
        console.error("AI Agent: Could not determine Room ID."); // 日志使用英文
        return; // 如果找不到房间 ID，则停止脚本执行
    }
    console.log(`AI Agent: Initialized for Room ID: ${roomId}`); // 日志使用英文

    createControlPanel(); // 创建控制面板
    observeVideoElement(); // 开始观察视频元素的出现

    // --- 函数 ---

    /**
     * 从当前 URL 中提取房间 ID。
     * @returns {string|null} 房间 ID，如果找不到则返回 null。
     */
    function getRoomId() {
        const match = window.location.pathname.match(/\/(\d+)/);
        return match ? match[1] : null;
    }

    /**
     * 创建控制面板 UI 并注入到页面中。
     */
    function createControlPanel() {
        // --- 注入样式 ---
        const style = document.createElement('style');
        style.textContent = `
        /* --- UI 面板样式 --- */
        .auto-chat-ai-panel {
            position: fixed;
            top: 20px;
            right: 20px;
            width: 240px;
            background-color: rgba(245, 245, 245, 0.55);
            backdrop-filter: blur(6px);
            border-radius: 12px;
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
            font-family: Arial, sans-serif;
            z-index: 10000;
            user-select: none;
            overflow: visible; /* ← 允许 tooltip 溢出 */
        }
        .panel-header {
            padding: 12px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: rgba(255, 255, 255, 0.95);
            cursor: grab;
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
        }
        .panel-title {
            font-size: 16px;
            font-weight: 600;
            color: #222;
        }
        .panel-menu {
            cursor: pointer;
            font-size: 18px;
            color: #444;
        }
        .panel-content {
            padding: 16px;
            background-color: rgba(245, 245, 245, 0.55);
            border-bottom-left-radius: 12px;   /* ← 给底部圆角 */
            border-bottom-right-radius: 12px;  /* ← 同上 */
        }
        .control-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
        }
        .control-label {
            font-size: 14px;
            color: #444;
            margin-right: 10px;
        }
        .switch {
            position: relative;
            display: inline-block;
            width: 40px;
            height: 20px;
        }
        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .slider-switch {
            position: absolute;
            cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: #ccc;
            transition: background-color 0.3s, transform 0.2s ease-in-out;
            border-radius: 20px;
        }
        .slider-switch:before {
            position: absolute;
            content: "";
            height: 16px;
            width: 16px;
            left: 2px;
            bottom: 2px;
            background-color: white;
            transition: transform 0.2s ease-in-out;
            border-radius: 50%;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }
        input:checked + .slider-switch {
            background-color: #4285f4;
        }
        input:checked + .slider-switch:before {
            transform: translateX(20px);
        }
        .volume-slider {
            width: 100%;
            margin-top: 8px;
            appearance: none;
            height: 4px;
            background: #bbb;
            border-radius: 2px;
        }
        .volume-slider:hover {
            opacity: 1;
        }
        .volume-slider::-webkit-slider-thumb,
        .volume-slider::-moz-range-thumb {
            width: 16px;
            height: 16px;
            background: #4285f4;
            cursor: pointer;
            border-radius: 50%;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }
        .run-button {
            width: 100%;
            padding: 12px 16px;
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 24px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            margin-top: 10px;
            transition: background-color 0.2s;
        }
        .run-button.running {
            background-color: #ea4335;
        }
        .run-button:disabled {
            background-color: #9ca3af;
            cursor: not-allowed;
        }

        /* --- Tooltip --- */
        .tooltip-container {
            position: relative;
            display: inline-block;
        }
        .tooltip-icon {
            display: inline-block;
            width: 16px;
            height: 16px;
            background-color: #888;
            color: #fff;
            font-size: 12px;
            font-weight: bold;
            border-radius: 50%;
            text-align: center;
            line-height: 16px;
            margin-left: 4px;
            cursor: help;
            transition: background-color 0.2s;
        }
        .tooltip-icon:hover {
            background-color: #555;
        }
        .tooltip-text {
            visibility: hidden;
            width: max-content;
            max-width: 200px;
            background-color: #333;
            color: #fff;
            text-align: left;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 12px;
            line-height: 1.4;
            position: absolute;
            z-index: 10001;
            bottom: 125%;
            left: 50%;
            transform: translateX(-50%);
            opacity: 0;
            transition: opacity 0.2s ease-in-out;
            white-space: pre-line;
        }
        .tooltip-container:hover .tooltip-text {
            visibility: visible;
            opacity: 1;
        }
    `;
        document.head.appendChild(style);

        // --- 构建面板 ---
        panel = document.createElement('div');
        panel.className = 'auto-chat-ai-panel';
        panel.innerHTML = `
        <div class="panel-header">
            <span class="panel-title">Live Stream Chat Agent</span>
            <span class="panel-menu" title="Menu">⋮</span>
        </div>
        <div class="panel-content">
            <div class="control-item">
                <span class="control-label">Control</span>
                <label class="switch">
                    <input type="checkbox" id="main-switch">
                    <span class="slider-switch"></span>
                </label>
            </div>
            <div class="control-item">
                <span class="control-label">Chat Permission</span>
                <label class="switch">
                    <input type="checkbox" id="chat-permission">
                    <span class="slider-switch"></span>
                </label>
            </div>
            <div class="control-item">
                <span class="control-label">
                    Mute
                    <span class="tooltip-container">
                        <span class="tooltip-icon">!</span>
                        <span class="tooltip-text">Does not affect AI Agent operation.</span>
                    </span>
                </span>
                <label class="switch">
                    <input type="checkbox" id="mute-audio">
                    <span class="slider-switch"></span>
                </label>
            </div>
            <div class="control-item">
                <span class="control-label">
                    Volume
                    <span class="tooltip-container">
                        <span class="tooltip-icon">!</span>
                        <span class="tooltip-text">Does not affect AI Agent operation.</span>
                    </span>
                </span>
            </div>
            <input type="range" id="volume-slider" class="volume-slider" min="0" max="100" value="50">
            <button id="run-button" class="run-button" disabled>Start</button>
        </div>
    `;
        document.body.appendChild(panel);

        // --- 绑定元素 ---
        const mainSwitch = panel.querySelector('#main-switch');
        const chatPermissionSwitch = panel.querySelector('#chat-permission');
        const muteAudioSwitch = panel.querySelector('#mute-audio');
        volumeSlider = panel.querySelector('#volume-slider');
        runButton = panel.querySelector('#run-button');

        // --- 事件监听 ---
        mainSwitch.addEventListener('change', () => {
            isMainSwitchOn = mainSwitch.checked;
            runButton.disabled = !isMainSwitchOn;
            if (!isMainSwitchOn && isAgentRunning) stopAgent();
        });

        chatPermissionSwitch.addEventListener('change', () => {
            isChatPermissionGranted = chatPermissionSwitch.checked;
            if (!isChatPermissionGranted) chatQueue = [];
        });

        muteAudioSwitch.addEventListener('change', () => {
            isMuted = muteAudioSwitch.checked;
            updateGain();
        });

        volumeSlider.addEventListener('input', () => {
            if (!isMuted) updateGain();
        });

        runButton.addEventListener('click', () => {
            if (isAgentRunning) stopAgent();
            else if (isMainSwitchOn) startAgent();
        });

        // --- 拖动逻辑 ---
        const header = panel.querySelector('.panel-header');
        let isDragging = false, startX = 0, startY = 0, origX = 0, origY = 0;
        header.addEventListener('mousedown', e => {
            if (e.button !== 0) return;
            isDragging = true;
            startX = e.clientX; startY = e.clientY;
            const rect = panel.getBoundingClientRect();
            origX = rect.left; origY = rect.top;
            panel.style.transition = 'none';
            document.body.style.userSelect = 'none';
            header.style.cursor = 'grabbing';
        });
        document.addEventListener('mousemove', e => {
            if (!isDragging) return;
            panel.style.left = origX + (e.clientX - startX) + 'px';
            panel.style.top = origY + (e.clientY - startY) + 'px';
        });
        document.addEventListener('mouseup', e => {
            if (e.button !== 0) return;
            isDragging = false;
            panel.style.transition = '';
            document.body.style.userSelect = '';
            header.style.cursor = 'grab';
        });
    }

    /**
     * 启动 AI 代理的核心逻辑。
     */
    function startAgent() {
        if (isAgentRunning) {
            console.warn("Agent is already running.");
            return;
        }
        if (!isMainSwitchOn) {
            console.warn("Cannot start agent, Master Control is OFF.");
            return;
        }

        console.log("Starting AI Agent...");
        if (initializeAudio()) { // 初始化音频成功
            isAgentRunning = true; // 设置代理运行状态标志
            startRecordingCycle(); // 开始录制循环
            // 更新按钮状态
            runButton.textContent = 'Stop'; // 中文
            runButton.classList.add('running');
            console.log("AI Agent started successfully.");
        } else { // 初始化音频失败
            console.error("Failed to initialize audio. Agent cannot start.");
            alert("错误：无法访问视频音频。请确保直播正在播放。"); // 中文提示
            // 保持按钮和开关的状态（用户需要修复问题）
            isAgentRunning = false; // 确保运行状态为 false
            runButton.textContent = 'Start'; // 中文
            runButton.classList.remove('running');
            // 可以考虑禁用按钮，直到问题解决，或者让用户重试
            // runButton.disabled = true;
        }
    }

    /**
     * 停止 AI 代理的核心逻辑。
     */
    function stopAgent() {
        if (!isAgentRunning) {
            console.warn("Agent is not running.");
            return;
        }
        console.log("Stopping AI Agent...");
        isAgentRunning = false; // 清除代理运行状态标志 *先于* 停止录制器

        stopRecordingAndProcessing(); // 停止录制和处理流程

        // 更新按钮状态
        runButton.textContent = 'Start'; // 中文
        runButton.classList.remove('running');
        // 确保主开关打开时，按钮是可用的
        if (isMainSwitchOn) {
            runButton.disabled = false;
        }

        console.log("AI Agent stopped.");
    }

    /**
     * 在页面上查找视频元素。
     * Bilibili 可能使用 <video> 或自定义元素如 <bwp-video>。
     * @returns {HTMLVideoElement|null} 视频元素或 null。
     */
    function findVideoElement() {
        // 如果 Bilibili 更改结构，需要调整选择器
        return document.querySelector('video, bwp-video video');
    }

    /**
     * 设置 MutationObserver 以检测视频元素何时添加到 DOM 中。
     */
    function observeVideoElement() {
        const targetNode = document.body;
        const config = { childList: true, subtree: true };

        const observer = new MutationObserver((mutationsList, obs) => {
            const videoElement = findVideoElement();
            if (videoElement) {
                console.log('AI Agent: Video element detected.');
                obs.disconnect(); // 一旦找到就停止观察
                // 视频元素找到后，如果主开关是开的，则自动启用运行按钮
                if (isMainSwitchOn && runButton) {
                    runButton.disabled = false;
                }
            }
        });

        // 初始检查，以防元素已经存在
        if (findVideoElement()) {
            console.log('AI Agent: Video element already present.');
            if (isMainSwitchOn && runButton) {
                runButton.disabled = false;
            }
        } else {
            console.log('AI Agent: Observing for video element...');
            observer.observe(targetNode, config);
        }
    }

    /**
     * 初始化 AudioContext 并连接视频元素源。
     * @returns {boolean} 如果初始化成功则为 true，否则为 false。
     */
    function initializeAudio() {
        const videoElement = findVideoElement();
        if (!videoElement) {
            console.error("Cannot initialize audio: Video element not found.");
            return false;
        }
        // 确保视频正在播放或准备播放以获取音轨
        if (videoElement.readyState < 2) { // 理想情况下需要 HAVE_METADATA 或更高
            console.warn("Video element not ready yet (readyState < 2). Audio might not be available immediately.");
        }

        try {
            // 如果 AudioContext 不存在或已关闭，则创建新的
            if (!audioContext || audioContext.state === 'closed') {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                console.log("AudioContext created or recreated.");
            }
            // 如果 AudioContext 被挂起（例如，由于用户交互），尝试恢复
            if (audioContext.state === 'suspended') {
                audioContext.resume().then(() => {
                    console.log("AudioContext resumed successfully.");
                }).catch(e => {
                    console.error("Failed to resume AudioContext:", e);
                });
            }

            // 仅当节点不存在时才创建它们
            if (!destination) {
                destination = audioContext.createMediaStreamDestination(); // 创建录音目标节点
                console.log("MediaStreamAudioDestinationNode created.");
            }
            // 每次都尝试重新连接源，以防视频元素被替换
            if (mediaElementSource) {
                mediaElementSource.disconnect(); // 断开旧连接
            }
            mediaElementSource = audioContext.createMediaElementSource(videoElement); // 从视频创建源节点
            console.log("MediaElementAudioSourceNode created/reconnected.");

            if (!gainNode) {
                gainNode = audioContext.createGain(); // 创建音量控制节点
                console.log("GainNode created.");
            }

            // 设置音频处理管线:
            // 视频 -> 音量控制 -> 录音目标 (用于录制)
            // 视频 -> 音量控制 -> 实际输出 (用于收听)
            mediaElementSource.connect(gainNode);
            gainNode.connect(destination); // 连接音量节点到录音目标
            gainNode.connect(audioContext.destination); // 连接音量节点到实际扬声器

            console.log("Audio nodes connected.");
            updateGain(); // 根据 UI 设置初始音量
            return true;
        } catch (error) {
            console.error("Error initializing audio context or nodes:", error);
            // 清理可能部分创建的元素
            if (gainNode) gainNode.disconnect();
            if (mediaElementSource) mediaElementSource.disconnect();
            // audioContext = null; // 不设置为 null，以便下次尝试 resume 或 recreate
            destination = null;
            mediaElementSource = null;
            gainNode = null;
            return false;
        }
    }

    /**
     * 根据静音状态和音量滑块更新增益节点值。
     */
    function updateGain() {
        if (gainNode && audioContext) {
            try {
                const volume = isMuted ? 0 : volumeSlider.value / 100; // 静音则为0，否则为滑块值
                // 使用 B站 自己的音量接口可能更可靠，但这里保留 GainNode 控制逻辑
                gainNode.gain.setValueAtTime(volume, audioContext.currentTime); // 平滑设置音量
                // console.log(`Gain set to: ${volume}`); // Debug 日志英文
            } catch (e) {
                console.error("Error setting gain value:", e);
            }
        }
    }

    /**
    * 使用两个录制器开始连续录制循环。
    */
    function startRecordingCycle() {
        // 检查底层录制器是否已在运行（预防措施）
        if (isRecorder1Active || isRecorder2Active) {
            console.warn("Recording cycle already active (recorders running).");
            return;
        }
        if (!destination) {
            console.error("Cannot start recording cycle: Audio destination not initialized.");
            return;
        }

        console.log('Starting recording cycle...');

        // 确保创建录制器
        const options = { mimeType: 'audio/webm;codecs=opus' };
        try {
            // 每次启动循环时都创建新的 MediaRecorder 实例可能更健壮
            mediaRecorder1 = new MediaRecorder(destination.stream, options);
            mediaRecorder2 = new MediaRecorder(destination.stream, options);
            console.log("MediaRecorders created.");
        } catch (e) {
            console.error("Error creating MediaRecorder:", e);
            alert(`错误：浏览器不支持所需的音频格式 (${options.mimeType})。无法录制。`); // 中文提示
            stopAgent(); // 创建失败则停止代理
            return; // 停止进程
        }

        // 为两个录制器设置事件监听器
        setupMediaRecorder(mediaRecorder1, chunks1, 'Recorder 1', mediaRecorder2);
        setupMediaRecorder(mediaRecorder2, chunks2, 'Recorder 2', mediaRecorder1);

        // 启动第一个录制器
        startSpecificRecorder(mediaRecorder1);
    }

    /**
     * 配置 MediaRecorder 实例的事件处理程序。
     * @param {MediaRecorder} recorder - 录制器实例。
     * @param {Blob[]} chunks - 用于存储此录制器音频块的数组。
     * @param {string} label - 用于日志记录的标签（例如，'Recorder 1'）。
     * @param {MediaRecorder} nextRecorder - 在此录制器停止后要启动的录制器实例。
     */
    function setupMediaRecorder(recorder, chunks, label, nextRecorder) {
        recorder.ondataavailable = (event) => {
            // 当有音频数据可用时触发
            if (event.data.size > 0) {
                // console.log(`Audio data available from ${label}: ${event.data.size} bytes`); // Debug 日志英文
                chunks.push(event.data); // 将数据块存入数组
            }
        };

        recorder.onstart = () => {
            // 当录制开始时触发
            console.log(`${label} started recording.`);
            recordingStartTimestamp = Date.now(); // 标记此块的开始时间
            chunks.length = 0; // 清空块数组以用于新的录制段
        };

        recorder.onstop = async () => {
            // 当录制停止时触发
            console.log(`${label} stopped recording.`);
                        
            recordingEndTimestamp = Date.now();

            // 标记对应的录制器为非活动
            if (label === 'Recorder 1') isRecorder1Active = false;
            else isRecorder2Active = false;

            // 检查代理运行状态，而不是主开关状态，因为停止可能是由按钮触发的
            const shouldContinue = isAgentRunning;

            if (chunks.length > 0) {
                // 如果收集到了数据块
                const audioBlob = new Blob(chunks, { type: recorder.mimeType }); // 将数据块合并成 Blob
                if (audioBlob.size < 8192) { // 避免发送几乎为空的 Blob
                    console.warn(`${label}: Blob size is very small (${audioBlob.size} bytes), skipping send.`);
                } else {
                    const chats = collectChatMessages(); // 收集此录制期间的相关弹幕消息
                    const screenshotBlob = await captureScreenshot(); // 捕获屏幕截图
                    sendDataToServer(audioBlob, chats, screenshotBlob); // 发送数据
                }
                chunks.length = 0; // 处理后清空块数组
            } else {
                console.log(`${label}: No audio data recorded in this interval.`);
            }

            // 如果代理应该继续运行，启动 *另一个* 录制器以继续循环
            if (shouldContinue) {
                // 只有在另一个录制器也停止的情况下才启动下一个（避免双重启动）
                if (!isRecorder1Active && !isRecorder2Active) {
                    startSpecificRecorder(nextRecorder);
                } else {
                    // console.log(`Waiting for the other recorder to stop before starting ${nextRecorder === mediaRecorder1 ? 'Recorder 1' : 'Recorder 2'}`);
                }
            } else {
                // 如果代理已被停止（通过 stopAgent 函数），则不启动下一个录制器
                console.log("Agent run state is false, not starting next recorder.");
                // 确保所有录制标志都为 false
                isRecorder1Active = false;
                isRecorder2Active = false;
                // 停止时 UI 状态已在 stopAgent 中处理，此处无需重复
            }
        };

        recorder.onerror = (event) => {
            // 当发生错误时触发
            console.error(`${label} error:`, event.error);
            // 标记对应的录制器为非活动
            if (label === 'Recorder 1') isRecorder1Active = false;
            else isRecorder2Active = false;

            // 尝试恢复？也许停止一切并发出错误信号。
            alert(`录制器 ${label} 发生错误。请检查控制台并可能需要重启代理。`); // 中文提示
            stopAgent(); // 在错误时停止整个代理
        };
    }

    /**
     * 启动特定的 MediaRecorder 并设置其超时。
     * 确保只有在代理运行时才启动，并更新活动标志。
     * @param {MediaRecorder} recorderToStart - 要启动的录制器实例。
     */
    function startSpecificRecorder(recorderToStart) {
        // 再次检查代理运行状态，以防在 onstop 和此调用之间状态改变
        if (!isAgentRunning) {
            console.log("Preventing recorder start because Agent run state is false.");
            isRecorder1Active = false; // 确保标志重置
            isRecorder2Active = false;
            return;
        }
        // 检查录制器是否已经是活动状态或非 'inactive' 状态
        if ((recorderToStart === mediaRecorder1 && isRecorder1Active) ||
            (recorderToStart === mediaRecorder2 && isRecorder2Active) ||
            recorderToStart.state !== 'inactive') {
            console.warn("Attempted to start a recorder that is already active or not inactive:", recorderToStart.state);
            return;
        }

        try {
            const label = recorderToStart === mediaRecorder1 ? 'Recorder 1' : 'Recorder 2';
            recorderToStart.start(); // 开始录制 (可能会抛出错误)

            // 设置活动标志
            if (label === 'Recorder 1') {
                isRecorder1Active = true;
                isRecorder2Active = false; // 确保另一个标志关闭
            } else {
                isRecorder2Active = true;
                isRecorder1Active = false; // 确保另一个标志关闭
            }
            console.log(`Successfully started ${label}`);

            // 定义停止函数，用于超时
            const stopFunction = () => {
                // 检查录制器实例是否存在且仍在录制中
                if (recorderToStart && recorderToStart.state === 'recording') {
                    console.log(`Timeout reached for ${label}, stopping...`);
                    try {
                        recorderToStart.stop(); // 停止录制（将触发 onstop）
                    } catch (stopError) {
                        console.error(`Error during ${label}.stop():`, stopError);
                        // 即使 stop 出错，也手动标记为非活动
                        if (label === 'Recorder 1') isRecorder1Active = false;
                        else isRecorder2Active = false;
                        stopAgent(); // 严重错误，停止代理
                    }
                } else {
                    // console.log(`${label} was already stopped or inactive when timeout triggered.`);
                    // 确保标志也是 false
                    if (label === 'Recorder 1') isRecorder1Active = false;
                    else isRecorder2Active = false;
                }
            };

            // 设置超时以停止此录制器
            if (label === 'Recorder 1') {
                clearTimeout(recorder1Timeout); // 清除任何之前的超时
                recorder1Timeout = setTimeout(stopFunction, RECORDING_INTERVAL_MS);
            } else {
                clearTimeout(recorder2Timeout); // 清除任何之前的超时
                recorder2Timeout = setTimeout(stopFunction, RECORDING_INTERVAL_MS);
            }

        } catch (startError) {
            console.error("Error starting recorder:", startError);
            alert("启动音频录制器失败。直播流可能已停止或发生内部错误。"); // 中文提示
            // 标记为非活动
            if (recorderToStart === mediaRecorder1) isRecorder1Active = false;
            else isRecorder2Active = false;
            stopAgent(); // 启动失败则停止代理
        }
    }

    /**
     * 完全停止两个录制器，清除超时，并重置相关状态。
     * 这个函数主要由 stopAgent 调用。
     */
    function stopRecordingAndProcessing() {
        console.log("Stopping recording cycle and clearing resources...");

        // 清除超时定时器
        clearTimeout(recorder1Timeout);
        clearTimeout(recorder2Timeout);

        // 安全地停止录制器（如果它们存在且处于活动状态）
        [mediaRecorder1, mediaRecorder2].forEach((recorder, index) => {
            if (recorder && recorder.state !== 'inactive') {
                try {
                    recorder.stop(); // 这个 stop 会触发 onstop，但我们已经设置 isAgentRunning 为 false，所以不会启动下一个
                    console.log(`Recorder ${index + 1} stopped via stopRecordingAndProcessing.`);
                } catch (e) {
                    console.warn(`Error stopping recorder ${index + 1}:`, e);
                }
            }
        });

        // 重置录制器活动标志
        isRecorder1Active = false;
        isRecorder2Active = false;

        // 清空数据块和累积状态
        chunks1 = [];
        chunks2 = [];
        accumulatedChunks = [];
        isAccumulating = false;
        // isSending 状态由 XHR 回调处理，这里不清，以防万一有请求在进行中

        // 理论上，录制器实例可以在这里销毁（设置为 null）以释放资源，
        // 但下次启动时会重新创建，所以不是必须的。
        // mediaRecorder1 = null;
        // mediaRecorder2 = null;

        console.log("Recording cycle fully stopped and resources cleared.");
    }

    /**
    * 从 DOM 中收集在最后录制间隔内的弹幕消息。
    * @returns {Array<object>} 弹幕消息对象的数组。
    */
    function collectChatMessages() {
        const newChats = [];
        // 查找弹幕元素，优先使用 .danmaku-item
        let chatElements = document.querySelectorAll('.danmaku-item');
        
        if (!chatElements || chatElements.length === 0) {
            chatElements = document.querySelectorAll('.chat-item'); // 备用选择器
            if (!chatElements || chatElements.length === 0) {
                console.warn("Could not find chat elements (tried .danmaku-item, .chat-item). Chat collection might fail.");
                return newChats;
            } else {
                // console.log("Using fallback selector '.chat-item' for chat messages."); // Debug 日志英文
            }
        }

        const startSec = Math.floor(recordingStartTimestamp / 1000);
        const endSec = Math.floor(recordingEndTimestamp / 1000);
        const effectiveEndSec = Math.max(endSec, startSec);
        console.log(`[Chat Collector] Interval: ${startSec} - ${effectiveEndSec}`);
        // console.log(`Collecting chats between ${startSec} and ${effectiveEndSec} seconds epoch.`); // Debug 日志英文

        chatElements.forEach(chatElement => {
            try {
                // 尝试获取时间戳 (data-ts 似乎更常见于 B站弹幕)
                const timestampAttr = chatElement.getAttribute('data-ts') || chatElement.getAttribute('data-timestamp');
                let timestamp = NaN;
                let isInTimeWindow = true; // 如果没有时间戳，默认包含？取决于需求

                if (timestampAttr) {
                    timestamp = parseInt(timestampAttr, 10);
                    if (!isNaN(timestamp)) {
                        // 转换毫秒时间戳为秒
                        if (timestamp > 1e12) timestamp = Math.floor(timestamp / 1000);
                        isInTimeWindow = (timestamp >= startSec && timestamp <= effectiveEndSec);
                    } else {
                        isInTimeWindow = false; // 无效时间戳则不包含
                    }
                } else {
                    // console.warn("Chat element missing timestamp attribute (data-ts/data-timestamp)."); // Debug 日志英文
                    // isInTimeWindow = true; // 取消注释以在没有时间戳时包含所有弹幕
                    isInTimeWindow = false; // 保持 false 以严格按时间过滤
                }

                if (isInTimeWindow) {
                    // 获取 UID 和用户名
                    const uid = chatElement.getAttribute('data-uid');
                    const uname = chatElement.getAttribute('data-uname');
                    // 获取弹幕内容
                    const contentNode = chatElement.querySelector('.danmaku-content')
                        || chatElement.querySelector('.danmaku-item-content')
                        || chatElement.querySelector('.danmaku-message') // 另一个可能的选择器
                        || chatElement; // 最后尝试整个元素
                    let content = contentNode ? contentNode.innerText.trim() : null;

                    // 如果直接从 chatElement 获取文本，尝试清理
                    if (content && chatElement === contentNode && uname && content.startsWith(uname)) {
                        content = content.substring(uname.length).replace(/^[:：\s]+/, '').trim();
                    }

                    if (uid && uname && content) {
                        newChats.push({
                            uname: uname,
                            content: content,
                            uid: uid,
                            timestamp: isNaN(timestamp) ? null : timestamp // 发送时间戳（如果可用）以供参考
                        });
                    } else {
                        // console.warn("Skipping chat item due to missing data:", { uid, uname, content: content ? 'exists' : 'missing', timestamp }); // Debug 日志英文
                    }
                }
            } catch (e) {
                console.error("Error processing a chat element:", e, chatElement);
            }
        });

        console.log(`Collected ${newChats.length} relevant chat messages for the interval.`);
        return newChats;
    }

    /**
     * 捕获当前视频帧的屏幕截图。
     * @returns {Promise<Blob|null>} 一个 Promise，解析为截图 Blob (JPEG) 或在错误时为 null。
     */
    async function captureScreenshot() {
        const videoElement = findVideoElement();
        if (!videoElement || videoElement.readyState < 1) {
            console.warn('Video element not found or not ready for screenshot.');
            return null;
        }

        const canvas = document.createElement('canvas');
        canvas.width = SCREENSHOT_WIDTH;
        canvas.height = SCREENSHOT_HEIGHT;

        try {
            const ctx = canvas.getContext('2d');
            ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height); // 绘制视频帧

            return new Promise((resolve) => {
                canvas.toBlob((blob) => {
                    // if (!blob) {
                    //    console.error("Canvas toBlob returned null.");
                    // }
                    resolve(blob); // 解析 Promise 返回 Blob 或 null
                }, 'image/jpeg', SCREENSHOT_QUALITY); // 指定格式和质量
            });
        } catch (error) {
            console.error('Error capturing screenshot:', error);
            return null; // 如果绘制或 Blob 创建失败，则返回 null
        }
    }

    /**
     * 将音频、弹幕消息和截图发送到后端 API。
     * 处理累积逻辑。
     * @param {Blob} audioBlob - 录制的音频数据。
     * @param {Array<object>} chats - 收集到的弹幕消息对象数组。
     * @param {Blob|null} screenshotBlob - 捕获的屏幕截图 blob，或 null。
     */
    function sendDataToServer(audioBlob, chats, screenshotBlob) {
        if (!audioBlob || audioBlob.size === 0) {
            console.log("No valid audio data to send.");
            return;
        }

        // 处理累积逻辑
        if (isSending) {
            console.log('Previous request in progress. Accumulating audio chunk...');
            if (!isAccumulating) {
                accumulatedChunks = [audioBlob]; // 开始新的累积
                isAccumulating = true;
            } else {
                accumulatedChunks.push(audioBlob); // 添加到现有累积中
            }
            // 简单起见，不累积弹幕和截图
            return;
        }

        // 合并累积的块
        let finalAudioBlob = audioBlob;
        if (isAccumulating && accumulatedChunks.length > 0) {
            console.log(`Merging ${accumulatedChunks.length} accumulated audio chunks with the current one.`);
            accumulatedChunks.push(audioBlob);
            finalAudioBlob = new Blob(accumulatedChunks, { type: audioBlob.type });
            accumulatedChunks = [];
            isAccumulating = false;
            console.log(`Merged audio blob size: ${finalAudioBlob.size} bytes`);
        }

        // --- 准备并发送数据 ---
        isSending = true; // 设置发送锁
        console.log(`Preparing to send data. Audio size: ${finalAudioBlob.size}`);

        // 不再需要 FileReader 预读和检查 header，直接发送 Blob
        const formData = new FormData();
        formData.append('audio', finalAudioBlob, `audio_${Date.now()}.webm`); // 使用 Blob 对象
        formData.append('chats', JSON.stringify(chats));
        formData.append('roomId', roomId);
        if (screenshotBlob) {
            const timestampStr = new Date().toISOString().replace(/[:.]/g, "-");
            const screenshotFilename = `${roomId}_${timestampStr}.jpg`;
            formData.append('screenshot', screenshotBlob, screenshotFilename);
        }

        // console.log('[DEBUG] FormData prepared for sending.'); // Debug 日志英文

        // --- 使用 XMLHttpRequest 发送 ---
        const xhr = new XMLHttpRequest();
        xhr.open('POST', API_ENDPOINT, true);
        xhr.timeout = 60000; // 设置超时

        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) { // 请求完成
                console.log(`[XHR] Upload complete. Status: ${xhr.status}`);
                // 首先释放锁，然后再处理后续逻辑
                isSending = false;

                if (xhr.status === 200) {
                    try {
                        const response = JSON.parse(xhr.responseText);
                        if (response.status === 'success') {
                            console.log('Server processed data successfully.');
                            console.log('> Recognized text:', response.recognized_text || "N/A");
                            console.log('> AI Response:', response.LLM_response || "N/A");

                            // 排队发送 AI 回复
                            let msgContents = response.msg_contents;
                            if (Array.isArray(msgContents) && msgContents.length > 0) {
                                if (isChatPermissionGranted) {
                                    console.log(`Queueing ${msgContents.length} message(s) from AI.`);
                                    msgContents.forEach(msgContent => {
                                        if (typeof msgContent === 'string' && msgContent.trim()) {
                                            chatQueue.push(...splitMessage(msgContent.trim()));
                                        }
                                    });
                                    processChatQueue(); // 开始处理队列
                                } else {
                                    console.log("AI provided messages, but chat permission is OFF. Messages discarded.");
                                }
                            } else {
                                console.log('No actionable chat messages received from AI.');
                            }
                        } else {
                            console.error('Server returned an error status:', response.message || "No message provided.");
                        }
                    } catch (e) {
                        console.error('Failed to parse JSON response:', e);
                        console.error('Raw Response:', xhr.responseText);
                    }
                } else {
                    console.error(`Failed to send data. HTTP Status: ${xhr.status} ${xhr.statusText}`);
                    console.error('Response Text:', xhr.responseText);
                }
                // 无论成功或失败，检查是否需要处理累积的块
                if (isAccumulating && accumulatedChunks.length > 0) {
                    console.log("Processing accumulated chunks immediately after send completion.");
                    const nextBlob = accumulatedChunks.shift();
                    if (accumulatedChunks.length === 0) isAccumulating = false;
                    console.warn("Sending accumulated audio chunk without fresh chat/screenshot context.");
                    // 注意：这里没有传递新的 chats 和 screenshotBlob
                    sendDataToServer(nextBlob, [], null);
                }
            }
        };

        xhr.onerror = function () { // 网络错误
            console.error('[XHR] Network error occurred during upload.');
            isSending = false; // 释放锁
            if (isAccumulating && accumulatedChunks.length > 0) {
                console.log("Processing accumulated chunks after network error.");
                const nextBlob = accumulatedChunks.shift();
                if (accumulatedChunks.length === 0) isAccumulating = false;
                console.warn("Sending accumulated audio chunk without fresh chat/screenshot context.");
                sendDataToServer(nextBlob, [], null);
            }
        };

        xhr.ontimeout = function () { // 请求超时
            console.error('[XHR] Request timed out.');
            isSending = false; // 释放锁
            if (isAccumulating && accumulatedChunks.length > 0) {
                console.log("Processing accumulated chunks after timeout.");
                const nextBlob = accumulatedChunks.shift();
                if (accumulatedChunks.length === 0) isAccumulating = false;
                console.warn("Sending accumulated audio chunk without fresh chat/screenshot context.");
                sendDataToServer(nextBlob, [], null);
            }
        };

        xhr.send(formData); // 发送数据
        console.log('Data sent to server.');
    }

    /**
     * 将长消息分割成适合弹幕发送的较短部分。
     * @param {string} message - 要分割的消息。
     * @returns {string[]} 消息部分的数组。
     */
    function splitMessage(message) {
        const parts = [];
        if (!message) return parts; // 如果消息为空，返回空数组
        for (let i = 0; i < message.length; i += MAX_CHAT_LENGTH) { // 按最大长度分割
            parts.push(message.slice(i, i + MAX_CHAT_LENGTH));
        }
        return parts;
    }

    /**
     * 处理弹幕队列，一次发送一条消息，并带有延迟。
     */
    function processChatQueue() {
        if (chatQueue.length === 0) {
            // console.log("Chat queue is empty."); // Debug 日志英文
            return;
        }
        // 在发送前再次检查权限
        if (!isChatPermissionGranted) {
            console.log("Chat permission is OFF. Clearing remaining queue.");
            chatQueue = [];
            return;
        }

        const message = chatQueue.shift(); // 从队列前面取出下一条消息
        console.log(`Processing chat queue. Remaining: ${chatQueue.length}. Next message: "${message}"`);

        sendChatMessage(message) // 发送弹幕消息
            .then(() => {
                console.log(`Successfully sent chat: "${message}"`);
                // 安排下一条消息（如果队列中还有）
                if (chatQueue.length > 0) {
                    const delay = getRandomInt(CHAT_SEND_DELAY_MIN_MS, CHAT_SEND_DELAY_MAX_MS);
                    console.log(`Scheduling next chat message in ${delay}ms`);
                    setTimeout(processChatQueue, delay);
                }
            })
            .catch(error => {
                console.error(`Failed to send chat message: "${message}". Error:`, error);
                // 失败后仍尝试处理队列中的下一个（可以考虑重试逻辑）
                if (chatQueue.length > 0) {
                    const delay = getRandomInt(CHAT_SEND_DELAY_MIN_MS, CHAT_SEND_DELAY_MAX_MS);
                    setTimeout(processChatQueue, delay);
                }
            });
    }

    /**
     * 在 Bilibili 界面中模拟输入和发送弹幕消息。
     * @param {string} message - 要发送的消息字符串。
     * @returns {Promise<void>} 一个 promise，在消息发送时解析，或在错误时拒绝。
     */
    /**
     * 在 Bilibili 界面中模拟输入和发送弹幕消息。
     * @param {string} message - 要发送的消息字符串。
     * @returns {Promise<void>} 一个 promise，在消息发送时解析，或在错误时拒绝。
     */
    function sendChatMessage(message) {
        return new Promise((resolve, reject) => {
            if (!message) {
                return reject(new Error("Cannot send empty message."));
            }
            if (!isChatPermissionGranted) {
                console.warn("Attempted to send chat message, but permission is OFF.");
                return resolve();
            }

            // 更强兼容性的输入框与按钮选择器
            const chatInput =
                document.querySelector('.chat-input-panel textarea.chat-input') ||
                document.querySelector('textarea.chat-input') ||
                document.querySelector('textarea');

            const sendButton =
                document.querySelector('button.bl-button.live-skin-highlight-button-bg') ||
                document.querySelector('button.bl-button--primary') ||
                document.querySelector('button');

            if (!chatInput) {
                return reject(new Error("Chat input element not found. Cannot send message."));
            }
            if (!sendButton) {
                return reject(new Error("Chat send button not found. Cannot send message."));
            }

            if (sendButton.disabled || sendButton.classList.contains('disabled') || sendButton.classList.contains('bl-button--disabled')) {
                console.warn("Chat send button is disabled (cooldown?). Will retry queue later.");
                chatQueue.unshift(message);
                setTimeout(processChatQueue, getRandomInt(3000, 5000));
                return reject(new Error("Send button disabled, rescheduling queue."));
            }

            console.log(`Attempting to send chat: "${message}"`);

            try {
                const inputEvent = new Event('input', { bubbles: true, cancelable: true });
                const changeEvent = new Event('change', { bubbles: true, cancelable: true });

                chatInput.focus();
                chatInput.value = message;
                chatInput.dispatchEvent(inputEvent);
                chatInput.dispatchEvent(changeEvent);

                setTimeout(() => {
                    if (!sendButton.disabled && !sendButton.classList.contains('disabled') && !sendButton.classList.contains('bl-button--disabled')) {
                        sendButton.click();
                        resolve();
                    } else {
                        console.warn("Send button became disabled just before clicking.");
                        chatQueue.unshift(message);
                        setTimeout(processChatQueue, getRandomInt(3000, 5000));
                        reject(new Error("Send button became disabled, rescheduling queue."));
                    }
                }, 150);

            } catch (error) {
                console.error("Error during chat simulation:", error);
                chatQueue.unshift(message);
                setTimeout(processChatQueue, getRandomInt(5000, 8000));
                reject(error);
            }
        });
    }

    /**
     * 生成介于 min 和 max（含）之间的随机整数。
     * @param {number} min 最小值。
     * @param {number} max 最大值。
     * @returns {number} 一个随机整数。
     */
    function getRandomInt(min, max) {
        min = Math.ceil(min); // 向上取整
        max = Math.floor(max); // 向下取整
        return Math.floor(Math.random() * (max - min + 1)) + min; // 返回范围内的随机整数
    }

    // --- 脚本入口点 ---
    console.log("Live Stream Chat AI Agent script loaded.");

})(); // IIFE 结束
