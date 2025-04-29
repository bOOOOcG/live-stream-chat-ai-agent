// ==UserScript==
// @name         Live Stream Chat AI Agent
// @name:zh-CN   直播聊天室AI智能代理
// @version      1.2.0
// @description  An AI script for automatically sending chat messages and interacting with streamers on multiple platforms (Bilibili, YouTube). Records audio, chat, and screenshots, sends to backend for AI processing, and posts responses automatically.
// @description:zh-CN  一个基于 AI 的脚本，用于在多个直播平台（Bilibili, YouTube）自动发送弹幕消息并与主播互动。录制音频、弹幕、直播间画面，发送到后端进行 AI 处理，并自动发布 AI 生成的聊天内容。
// @description:zh-TW  一個基於人工智慧的腳本，用於在多個直播平台（Bilibili, YouTube）自動發送聊天室訊息並與主播互動。錄製音訊、彈幕和直播畫面，傳送到後端進行 AI 處理，並自動發佈聊天室內容。
// @description:zh-HK  一個基於人工智能的腳本，用於在多個直播平台（Bilibili, YouTube）自動發送聊天室訊息並與主播互動。錄製音訊、彈幕及直播畫面，傳送至後台進行 AI 分析處理，並自動發佈聊天室內容。
// @author       bOc
// @match        https://live.bilibili.com/*
// @match        https://www.youtube.com/watch*
// @match        https://www.twitch.tv/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    // --- 常量定义 ---
    const API_ENDPOINT = 'https://your_server_address:8181/upload'; // 后端 API 地址
    const RECORDING_INTERVAL_MS = 30000; // 30 秒 - 录制分块时长
    const MAX_CHAT_LENGTH = 20; // 每条弹幕消息分段的最大长度 (默认值 一般会被已知平台的最优值替代)
    const FORCE_CHAT_LENGTH = 0; // 0 = 不强制，如果大于0，比如10，就强制每10字符切割为一个弹幕
    const CHAT_SEND_DELAY_MIN_MS = 3000; // 发送弹幕消息之间的最小延迟（毫秒）
    const CHAT_SEND_DELAY_MAX_MS = 6000; // 发送弹幕消息之间的最大延迟（毫秒）
    const SCREENSHOT_WIDTH = 1280; // 期望的截图宽度
    const SCREENSHOT_HEIGHT = 720; // 期望的截图高度
    const SCREENSHOT_QUALITY = 0.9; // 截图 JPEG 质量 (0.0 到 1.0)

    // --- 平台适配器定义 ---
    const platformAdapters = {
        bilibili: {
            platformName: "Bilibili",
            isApplicable: () => window.location.hostname.includes('live.bilibili.com'),

            /**
             * 从当前 URL 中提取房间 ID。(Bilibili)
             * @returns {string|null} 房间 ID，如果找不到则返回 null。
             */
            getRoomId: () => {
                const match = window.location.pathname.match(/\/(\d+)/);
                return match ? match[1] : null;
            },

            /**
             * 在页面上查找视频元素。(Bilibili)
             * Bilibili 可能使用 <video> 或自定义元素如 <bwp-video>。
             * @returns {HTMLVideoElement|null} 视频元素或 null。
             */
            findVideoElement: () => {
                // 如果 Bilibili 更改结构，需要调整选择器
                return document.querySelector('video, bwp-video video');
            },

            /**
            * 从 DOM 中收集在最后录制间隔内的弹幕消息。(Bilibili)
            * @param {number} recordingStartTimestamp - 录制开始时间戳 (ms)
            * @param {number} recordingEndTimestamp - 录制结束时间戳 (ms)
            * @returns {Array<object>} 弹幕消息对象的数组。
            */
            collectChatMessages: (recordingStartTimestamp, recordingEndTimestamp) => {
                const newChats = []; // 初始化用于存储新弹幕的数组
                // 查找弹幕元素，优先使用 .danmaku-item
                let chatElements = document.querySelectorAll('.danmaku-item');

                // 如果找不到 .danmaku-item，尝试备用选择器 .chat-item
                if (!chatElements || chatElements.length === 0) {
                    chatElements = document.querySelectorAll('.chat-item');
                    if (!chatElements || chatElements.length === 0) {
                        console.warn("Bilibili 适配器: 找不到聊天元素 (尝试了 .danmaku-item, .chat-item)。聊天收集可能失败。");
                        return newChats; // 找不到则返回空数组
                    } else {
                        // console.log("Bilibili 适配器: 使用备用选择器 '.chat-item' 获取聊天消息。");
                    }
                }

                // 将录制开始和结束时间戳从毫秒转换为秒
                const startSec = Math.floor(recordingStartTimestamp / 1000);
                const endSec = Math.floor(recordingEndTimestamp / 1000);
                // 确保结束时间不早于开始时间（处理可能的边界情况）
                const effectiveEndSec = Math.max(endSec, startSec);

                // 【调试日志】打印请求的时间段（秒）
                // console.log(`[聊天收集器 - Bilibili] 请求的时间段 (秒): ${startSec} - ${effectiveEndSec}`);

                // 遍历找到的所有聊天元素
                chatElements.forEach(chatElement => {
                    let timestamp = null; // 初始化此聊天项的时间戳变量
                    let timestampAttr = null; // 存储原始时间戳属性字符串，用于调试
                    let isInTimeWindow = false; // 默认为不在时间窗口内

                    try {
                        // 尝试获取 data-ts 或 data-timestamp 属性
                        timestampAttr = chatElement.getAttribute('data-ts') || chatElement.getAttribute('data-timestamp');

                        if (timestampAttr) {
                            // 解析时间戳字符串为整数
                            const parsedTimestamp = parseInt(timestampAttr, 10);
                            // 检查解析是否成功 (不是 NaN)
                            if (!isNaN(parsedTimestamp)) {
                                // 如果时间戳看起来像毫秒（非常大），则转换为秒，否则假定已经是秒
                                timestamp = (parsedTimestamp > 1e12) ? Math.floor(parsedTimestamp / 1000) : parsedTimestamp;
                                // 检查时间戳是否落在有效的录制时间窗口内
                                isInTimeWindow = (timestamp >= startSec && timestamp <= effectiveEndSec);
                            }
                            // else: 解析为 NaN，timestamp 保持 null，isInTimeWindow 保持 false
                        }
                        // else: 元素上没有时间戳属性，timestamp 保持 null，isInTimeWindow 保持 false

                        // 【调试日志】在决定是否跳过之前，记录每条消息的详细信息
                        // const debugContent = (chatElement.querySelector('.danmaku-item-content') || chatElement).innerText?.slice(0, 50).trim();
                        // console.log(`[Bili 聊天项] 原始 TS 属性: ${timestampAttr}, 解析秒: ${timestamp}, 在窗口内 (${startSec}-${effectiveEndSec})?: ${isInTimeWindow}, 内容: ${debugContent || 'N/A'}`);

                        // 仅当消息在时间窗口内时才处理
                        if (isInTimeWindow) {
                            // 【调试日志】确认包含此消息
                            // console.log(` -> 包含 (时间戳 ${timestamp} 在 ${startSec}-${effectiveEndSec} 之内)`);

                            // --- 提取弹幕信息 ---
                            const uid = chatElement.getAttribute('data-uid'); // 获取用户ID
                            const uname = chatElement.getAttribute('data-uname'); // 获取用户名
                            // 尝试多种选择器获取弹幕内容节点
                            const contentNode = chatElement.querySelector('.danmaku-content')
                                || chatElement.querySelector('.danmaku-item-content')
                                || chatElement.querySelector('.danmaku-message')
                                || chatElement; // 最后尝试整个元素
                            // 获取并清理弹幕文本内容
                            let content = contentNode ? contentNode.innerText.trim() : null;

                            // B站有时会将用户名作为内容的前缀，尝试移除
                            if (content && chatElement === contentNode && uname && content.startsWith(uname)) {
                                content = content.substring(uname.length).replace(/^[:：\s]+/, '').trim();
                            }
                            // --- 提取结束 ---

                            // 确保 uid, uname, content 都有效
                            if (uid && uname && content) {
                                // 将提取的信息添加到 newChats 数组
                                newChats.push({
                                    uname: uname,
                                    content: content,
                                    uid: uid,
                                    platform: 'bilibili', // 标记来源平台
                                    // 发送我们用于过滤的时间戳（秒）
                                    timestamp: timestamp
                                });
                            } else {
                                // 如果缺少关键数据，则发出警告（可选）
                                // console.warn("Bilibili 适配器: 因缺少数据 (uid/uname/content) 跳过聊天项:", { uid, uname, content: content ? '存在' : '缺失', timestamp });
                            }
                        } else {
                            // 【调试日志】说明跳过此消息的原因
                            // console.log(` -> 跳过 (时间戳 ${timestamp} 在 ${startSec}-${effectiveEndSec} 之外或为 null/无效)`);
                        }
                    } catch (e) {
                        // 捕获并报告处理单个聊天元素时发生的错误
                        console.error("Bilibili 适配器: 处理聊天元素时出错:", e, chatElement);
                    }
                }); // 结束遍历

                // 【调试日志】打印最终收集到的相关聊天消息数量
                // console.log(`Bilibili 适配器: 为该时间段收集了 ${newChats.length} 条相关聊天消息。`);
                return newChats; // 返回收集到的聊天消息数组
            },

            /**
             * 在 Bilibili 界面中模拟输入和发送弹幕消息。(Bilibili)
             * @param {string} message - 要发送的消息字符串。
             * @returns {Promise<string>} 一个 promise，解析为状态字符串 ('success', 'disabled', 'error', 'not_found')。
             */
            sendChatMessage: async (message) => {
                return new Promise((resolve) => {
                    if (!message) {
                        console.error("Bilibili Adapter: Cannot send empty message.");
                        resolve('error');
                        return;
                    }
                    // 权限检查在核心逻辑中进行

                    // 更强兼容性的输入框与按钮选择器
                    const chatInput =
                        document.querySelector('.chat-input-panel textarea.chat-input') ||
                        document.querySelector('textarea.chat-input') ||
                        document.querySelector('textarea#chat-input-area') || // Another possible ID
                        document.querySelector('textarea[placeholder*="发个弹幕"]'); // Fallback by placeholder

                    const sendButton =
                        document.querySelector('button.bl-button.live-skin-highlight-button-bg.send-button') || // More specific send button
                        document.querySelector('div.bottom-actions button.bl-button--primary') ||
                        document.querySelector('button.bl-button--primary[type="submit"]') || // Try submit type
                        document.querySelector('[data-testid="send-button"]'); // Test ID if available

                    if (!chatInput) {
                        console.error("Bilibili Adapter: Chat input element not found.");
                        resolve('not_found');
                        return;
                    }
                    if (!sendButton) {
                        console.error("Bilibili Adapter: Chat send button not found.");
                        resolve('not_found');
                        return;
                    }

                    // 检查按钮是否明确禁用
                    const isDisabled = sendButton.disabled || sendButton.classList.contains('disabled') || sendButton.classList.contains('bl-button--disabled');

                    if (isDisabled) {
                        console.warn("Bilibili Adapter: Chat send button is disabled (cooldown?).");
                        resolve('disabled'); // 特殊状态码，表示按钮禁用
                        return;
                    }

                    console.log(`Bilibili Adapter: Attempting to send chat: "${message}"`);

                    try {
                        const inputEvent = new Event('input', { bubbles: true, cancelable: true });
                        const changeEvent = new Event('change', { bubbles: true, cancelable: true });

                        chatInput.focus();
                        chatInput.value = message;
                        chatInput.dispatchEvent(inputEvent);
                        chatInput.dispatchEvent(changeEvent);

                        // 短暂延迟后检查按钮状态并点击
                        setTimeout(() => {
                            // 再次检查禁用状态，以防在输入后被禁用
                            const stillEnabled = !sendButton.disabled && !sendButton.classList.contains('disabled') && !sendButton.classList.contains('bl-button--disabled');
                            if (stillEnabled) {
                                sendButton.click();
                                console.log(`Bilibili Adapter: Chat sent successfully (presumably): "${message}"`);
                                resolve('success');
                            } else {
                                console.warn("Bilibili Adapter: Send button became disabled just before clicking.");
                                resolve('disabled'); // 按钮在最后时刻被禁用
                            }
                        }, 150); // 稍作延迟给React等框架反应时间

                    } catch (error) {
                        console.error("Bilibili Adapter: Error during chat simulation:", error);
                        resolve('error'); // 模拟过程中出错
                    }
                });
            },
            // Bilibili 可能需要的其他特定函数
        },

        youtube: {
            platformName: "YouTube",
            isApplicable: () => window.location.hostname.includes('youtube.com') && window.location.pathname.startsWith('/watch'),

            /**
             * 异步提取 YouTube 频道用户名或 ID。
             * 支持 href="/@username" 和 href="/channel/UCxxx"。
             * 如果一开始取不到，会自动重试，直到成功或超时。
             * @returns {Promise<string|null>} 返回 Promise，解析为找到的频道 ID 或 null。
             */
            getRoomId: (() => {
                let cachedRoomId = null;
                let isSearching = false; // 防止重复搜索
                let waitingResolvers = [];

                return () => {
                    return new Promise(resolve => {
                        if (cachedRoomId) {
                            resolve(cachedRoomId);
                            return;
                        }

                        waitingResolvers.push(resolve);

                        if (isSearching) return;
                        isSearching = true;

                        let retries = 0;
                        const maxRetries = 10;
                        const retryInterval = 500; // ms

                        const selectors = [
                            '#upload-info ytd-channel-name a[href^="/@"]',
                            '#upload-info ytd-channel-name a[href^="/channel/"]',
                            'ytd-channel-name a[href^="/@"]',
                            'ytd-channel-name a[href^="/channel/"]',
                        ];

                        const tryFindRoomId = () => {
                            const link = selectors
                                .map(sel => document.querySelector(sel))
                                .find(el => el !== null);

                            if (link) {
                                const href = link.getAttribute('href');
                                const match = href.match(/^\/@([^/]+)/) || href.match(/^\/channel\/([^/]+)/);
                                if (match) {
                                    console.log("YouTube Adapter: Found channel ID/username:", match[1]);
                                    cachedRoomId = match[1];
                                    waitingResolvers.forEach(r => r(cachedRoomId));
                                    waitingResolvers = [];
                                    isSearching = false;
                                    return;
                                }
                            }

                            if (retries < maxRetries) {
                                retries++;
                                console.log(`YouTube Adapter: Retry finding channel ID/username (${retries}/${maxRetries})...`);
                                setTimeout(tryFindRoomId, retryInterval);
                            } else {
                                console.error("YouTube Adapter: Failed to find channel ID/username after retries.");
                                waitingResolvers.forEach(r => r(null));
                                waitingResolvers = [];
                                isSearching = false;
                            }
                        };

                        setTimeout(tryFindRoomId, 0);
                    });
                };
            })(),

            /**
             * 在页面上查找视频元素。(YouTube)
             * @returns {HTMLVideoElement|null} 视频元素或 null。
             */
            findVideoElement: () => {
                // YouTube 主要视频播放器通常的选择器
                const video = document.querySelector('#movie_player video.html5-main-video');
                if (!video) {
                    console.warn("YouTube Adapter: Could not find primary video element (#movie_player video.html5-main-video).");
                }
                return video;
            },

            /**
             * 从 DOM 中收集在最后录制间隔内的聊天消息。(YouTube)
             * @param {number} recordingStartTimestamp - 录制开始时间戳 (ms)
             * @param {number} recordingEndTimestamp - 录制结束时间戳 (ms)
             * @returns {Array<object>} 聊天消息对象的数组
             */
            collectChatMessages: (recordingStartTimestamp, recordingEndTimestamp) => {
                const newChats = [];
                const startSecYt = Math.floor(recordingStartTimestamp / 1000); // 仍然计算秒级，可能用于输出
                const endSecYt = Math.floor(recordingEndTimestamp / 1000);
                const effectiveEndSecYt = Math.max(endSecYt, startSecYt);

                const iframe = document.querySelector('iframe#chatframe');
                if (!iframe) { console.warn("YouTube 适配器: 未找到聊天 iframe (#chatframe)。"); return newChats; }
                const chatDoc = iframe.contentDocument || iframe.contentWindow?.document;
                if (!chatDoc) { console.warn("YouTube 适配器: 无法访问聊天 iframe 文档。"); return newChats; }

                // --- 1. 生成允许的时间字符串集合 ---
                const allowedVisibleTimestamps = new Set();
                try {
                    const startDate = new Date(recordingStartTimestamp);
                    const endDate = new Date(recordingEndTimestamp);

                    // 将开始时间调回到该分钟的开始 (0 秒, 0 毫秒)
                    let currentMinuteDate = new Date(startDate);
                    currentMinuteDate.setSeconds(0, 0);

                    // 获取结束时间对应的分钟的开始时间戳，用于循环比较
                    let endMinuteStartTimestamp = new Date(endDate);
                    endMinuteStartTimestamp.setSeconds(0, 0);
                    endMinuteStartTimestamp = endMinuteStartTimestamp.getTime();

                    // 循环生成从开始分钟到结束分钟的所有时间字符串
                    let iterations = 0; // 防止无限循环
                    const maxIterations = 1440; // 一天最多1440分钟

                    while (currentMinuteDate.getTime() <= endMinuteStartTimestamp && iterations < maxIterations) {
                        // 格式化时间，需要精确匹配 YouTube 的格式，注意 AM/PM 和可能存在的特殊空格
                        // 'en-US' 通常能得到 AM/PM 格式。 'narrowSymbol' (U+202F) 可能需要手动处理或正则替换
                        const options = { hour: 'numeric', minute: '2-digit', hour12: true };
                        let visibleStr = currentMinuteDate.toLocaleTimeString('en-US', options);
                        // 尝试标准化：去除多余空格并将 PM/AM 转为大写 (如果需要)
                        visibleStr = visibleStr.replace(/\s+/g, ' ').replace(/ (AM|PM)$/i, (match, p1) => ' ' + p1.toUpperCase());
                        // 特殊处理一下你例子中的特殊空格 U+202F (NARROW NO-BREAK SPACE)
                        visibleStr = visibleStr.replace(/[\u202F]/g, ' '); // 将特殊空格替换为普通空格
                        visibleStr = visibleStr.trim(); // 最后清理

                        allowedVisibleTimestamps.add(visibleStr);

                        // 前进一分钟
                        currentMinuteDate.setMinutes(currentMinuteDate.getMinutes() + 1);
                        iterations++;
                    }
                    if (iterations >= maxIterations) {
                        console.warn("YouTube 时间戳生成循环次数过多，可能存在问题。");
                    }
                    // console.log("[YT 计算] 允许的可见时间戳:", allowedVisibleTimestamps);

                } catch (err) {
                    console.error("[YT 错误] 生成允许的时间戳集合时出错:", err);
                    // 如果出错，则不进行过滤，收集所有消息（或返回空，取决于策略）
                    // 为了安全起见，这里返回空，避免发送错误数据
                    return newChats;
                }

                // 如果集合为空（可能开始结束时间相同且正好在分钟边界），至少加入开始时间对应的那个
                if (allowedVisibleTimestamps.size === 0) {
                    try {
                        const startDate = new Date(recordingStartTimestamp);
                        const options = { hour: 'numeric', minute: '2-digit', hour12: true };
                        let visibleStr = startDate.toLocaleTimeString('en-US', options);
                        visibleStr = visibleStr.replace(/\s+/g, ' ').replace(/ (AM|PM)$/i, (match, p1) => ' ' + p1.toUpperCase());
                        visibleStr = visibleStr.replace(/[\u202F]/g, ' ');
                        visibleStr = visibleStr.trim();
                        allowedVisibleTimestamps.add(visibleStr);
                        // console.log("[YT 计算] 集合为空，添加开始时间戳:", allowedVisibleTimestamps);
                    } catch (e) { /* Failsafe */ }
                }

                const chatItems = chatDoc.querySelectorAll(
                    'yt-live-chat-text-message-renderer, ' +
                    'yt-live-chat-paid-message-renderer, ' +
                    'yt-live-chat-paid-sticker-renderer, ' +
                    'yt-live-chat-membership-item-renderer'
                );

                chatItems.forEach((el, index) => {
                    let isAllowed = false;
                    let messageVisibleStr = '';
                    try {
                        // --- 2. 获取消息的可见时间戳 ---
                        const timestampSpan = el.querySelector('#timestamp');
                        if (timestampSpan) {
                            messageVisibleStr = timestampSpan.textContent.trim();
                            // 标准化处理，使其与我们生成的格式一致
                            messageVisibleStr = messageVisibleStr.replace(/\s+/g, ' '); // 替换各种空白为普通空格
                            messageVisibleStr = messageVisibleStr.replace(/[\u202F]/g, ' '); // 处理特殊空格 U+202F
                            messageVisibleStr = messageVisibleStr.replace(/ (AM|PM)$/i, (match, p1) => ' ' + p1.toUpperCase());
                            messageVisibleStr = messageVisibleStr.trim(); // 最后清理

                            // --- 3. 检查时间戳是否在允许的集合中 ---
                            isAllowed = allowedVisibleTimestamps.has(messageVisibleStr);
                            // console.log(`[YT 聊天项 #${index}] 可见时间: "${messageVisibleStr}", 在允许集合 (${[...allowedVisibleTimestamps].join(',')}) 中?: ${isAllowed}`);
                        } else {
                            // console.log(`[YT 聊天项 #${index}] 找不到可见时间戳 span#timestamp`);
                        }

                        if (isAllowed) {
                            // console.log(`          -> 包含此消息 (基于可见时间)`);
                            const authorName = el.querySelector('#author-name')?.textContent.trim() || '未知';
                            let message = '';
                            // ... (提取 message 的逻辑不变，和之前的版本一样) ...
                            if (el.matches('yt-live-chat-text-message-renderer')) {
                                const messageSpan = el.querySelector('#message');
                                if (messageSpan) {
                                    message = Array.from(messageSpan.childNodes).map(node => {
                                        if (node.nodeType === Node.TEXT_NODE) { return node.textContent.trim(); }
                                        if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'IMG') {
                                            const alt = node.getAttribute('alt')?.trim() ?? '表情'; return `[${alt}]`;
                                        } return '';
                                    }).join(' ').replace(/\s+/g, ' ').trim();
                                }
                            } else if (el.matches('yt-live-chat-paid-message-renderer')) {
                                const price = el.querySelector('#purchase-amount')?.textContent.trim() || '';
                                const paidMsg = el.querySelector('#message')?.innerText.trim() || '(无留言)';
                                message = `[SuperChat ${price}] ${paidMsg}`;
                            } else if (el.matches('yt-live-chat-paid-sticker-renderer')) {
                                const price = el.querySelector('#purchase-amount')?.textContent.trim() || '';
                                message = `[SuperSticker ${price}] [发送了超级贴图]`;
                            } else if (el.matches('yt-live-chat-membership-item-renderer')) {
                                const giftText = el.innerText.trim();
                                message = `[会员消息] ${giftText}`;
                            } else {
                                return; // 跳过未知类型
                            }

                            if (authorName && message) {
                                newChats.push({
                                    uname: authorName,
                                    content: message,
                                    platform: 'youtube',
                                    // --- 4. 输出时间戳：使用粗略的开始秒数作为占位符 ---
                                    timestamp: startSecYt
                                });
                            }
                        } else {
                            // console.log(`          -> 跳过 (可见时间 "${messageVisibleStr}" 不在允许集合中)`);
                        }
                    } catch (err) {
                        console.error(`[YT 聊天项 #${index}] 处理出错:`, err, el);
                    }
                }); // 结束遍历

                // console.log(`[YT 结果] 本次使用可见时间戳收集到 ${newChats.length} 条相关聊天消息。`);
                return newChats;
            },

            /**
             * 在 YouTube 界面中模拟输入和发送聊天消息。(YouTube)
             * @param {string} message - 要发送的消息字符串。
             * @returns {Promise<string>} 一个 promise，解析为状态字符串 ('success', 'disabled', 'error', 'not_found')
             */
            sendChatMessage: async (message) => {
                try {
                    const iframe = document.querySelector('iframe#chatframe');
                    if (!iframe) {
                        console.error("YouTube Adapter: Chat iframe (#chatframe) not found.");
                        return 'not_found';
                    }

                    const chatDoc = iframe.contentDocument || iframe.contentWindow?.document;
                    if (!chatDoc) {
                        console.error("YouTube Adapter: Cannot access chat iframe document.");
                        return 'not_found';
                    }

                    const inputRenderer = chatDoc.querySelector('yt-live-chat-text-input-field-renderer#input');
                    if (!inputRenderer) {
                        console.error("YouTube Adapter: Chat input renderer not found inside iframe.");
                        return 'not_found';
                    }

                    const chatInput = inputRenderer.shadowRoot?.querySelector('div#input[contenteditable]')
                        || inputRenderer.querySelector('div#input[contenteditable]');
                    if (!chatInput) {
                        console.error("YouTube Adapter: Contenteditable input not found.");
                        return 'not_found';
                    }

                    if (chatInput.offsetParent === null) {
                        console.warn("YouTube Adapter: Chat input is hidden or disabled.");
                        return 'disabled';
                    }

                    // 输入文字
                    chatInput.focus();
                    chatInput.innerText = message;

                    chatInput.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'insertText',
                        data: message
                    }));

                    console.log(`YouTube Adapter: Message "${message}" inputted, waiting for button to enable...`);

                    // 等待发送按钮
                    return await new Promise((resolve) => {
                        setTimeout(() => {
                            const sendButton = chatDoc.querySelector('yt-live-chat-message-input-renderer yt-button-renderer button');
                            if (!sendButton) {
                                console.error("YouTube Adapter: Send button not found.");
                                resolve('not_found');
                                return;
                            }

                            if (sendButton.disabled) {
                                console.warn("YouTube Adapter: Send button is still disabled.");
                                resolve('disabled');
                                return;
                            }

                            sendButton.click();
                            console.log(`YouTube Adapter: Chat message sent successfully: "${message}"`);
                            resolve('success');
                        }, 150); // 延迟150ms，保证按钮状态刷新
                    });

                } catch (err) {
                    console.error("YouTube Adapter: Error sending chat message", err);
                    return 'error';
                }
            },
            // YouTube 的其他特定函数
        },
        twitch: {
            platformName: "Twitch",

            /**
             * 判斷當前頁面是否為 Twitch 直播頁。
             * @returns {boolean}
             */
            isApplicable: () => {
                return window.location.hostname.includes('twitch.tv') && window.location.pathname.length > 1;
            },

            /**
             * 提取 Twitch 頻道名稱（用於作為 RoomId）。
             * @returns {string|null}
             */
            getRoomId: () => {
                const path = window.location.pathname;
                if (path && path.length > 1) {
                    return path.slice(1); // 去掉開頭的 '/'
                }
                return null;
            },

            /**
             * 查找 Twitch 上的視頻元素。
             * @returns {HTMLVideoElement|null}
             */
            findVideoElement: () => {
                const video = document.querySelector('video');
                if (!video) {
                    console.warn("Twitch Adapter: 無法找到 <video> 元素。");
                }
                return video;
            },

            /**
             * 收集在錄音起止時間範圍內的 Twitch 聊天消息。
             * @param {number} recordingStartTimestamp - 錄製開始時間戳 (ms)
             * @param {number} recordingEndTimestamp - 錄製結束時間戳 (ms)
             * @returns {Array<object>} 聊天消息列表
             */
            collectChatMessages: (recordingStartTimestamp, recordingEndTimestamp) => {
                const newChats = [];
                const chatElements = document.querySelectorAll('.chat-line__message');

                console.log(`[Twitch Adapter] 找到聊天元素数量: ${chatElements.length}`);

                if (!chatElements || chatElements.length === 0) {
                    console.warn("[Twitch Adapter] 未找到聊天訊息元素 .chat-line__message。");
                    return newChats;
                }

                const startDate = new Date(recordingStartTimestamp);
                const endDate = new Date(recordingEndTimestamp);
                const allowedVisibleTimestamps = new Set();

                console.log(`[Twitch Adapter] 錄音開始: ${startDate.toISOString()}，結束: ${endDate.toISOString()}`);

                // 生成從開始到結束分鐘的可見時間字符串集合
                try {
                    let currentMinuteDate = new Date(startDate);
                    currentMinuteDate.setSeconds(0, 0);

                    const endMinuteStartTimestamp = new Date(endDate);
                    endMinuteStartTimestamp.setSeconds(0, 0);

                    let iterations = 0;
                    const maxIterations = 1440; // 24小時上限
                    while (currentMinuteDate.getTime() <= endMinuteStartTimestamp.getTime() && iterations < maxIterations) {
                        const hh = currentMinuteDate.getHours().toString().padStart(2, '0');
                        const mm = currentMinuteDate.getMinutes().toString().padStart(2, '0');
                        allowedVisibleTimestamps.add(`${hh}:${mm}`);
                        currentMinuteDate.setMinutes(currentMinuteDate.getMinutes() + 1);
                        iterations++;
                    }
                    console.log(`[Twitch Adapter] 允許的時間戳範圍集合:`, [...allowedVisibleTimestamps]);
                } catch (err) {
                    console.error("[Twitch Adapter] 生成允許時間集合時出錯:", err);
                    return newChats;
                }

                chatElements.forEach((chatEl, idx) => {
                    try {
                        const timestampSpan = chatEl.querySelector('.chat-line__timestamp');
                        const usernameSpan = chatEl.querySelector('.chat-author__display-name');
                        const messageSpan = chatEl.querySelector('span[data-a-target="chat-message-text"]');

                        if (timestampSpan && usernameSpan && messageSpan) {
                            const visibleTime = timestampSpan.textContent.trim(); // 例如 '19:44'
                            console.log(`[Twitch Adapter] 第${idx + 1}個訊息: timestamp=${visibleTime}`);

                            if (allowedVisibleTimestamps.has(visibleTime)) {
                                const uname = usernameSpan.textContent.trim();
                                const content = messageSpan.textContent.trim();
                                console.log(`[Twitch Adapter] => 命中時間範圍，收集 uname=${uname}, content=${content}`);

                                if (uname && content) {
                                    newChats.push({
                                        uname: uname,
                                        content: content,
                                        platform: 'twitch',
                                        timestamp: Math.floor(recordingStartTimestamp / 1000) // 錄音開始秒數
                                    });
                                }
                            } else {
                                console.log(`[Twitch Adapter] => 時間不符合，跳過`);
                            }
                        } else {
                            console.warn(`[Twitch Adapter] 第${idx + 1}個訊息：缺少必要元素 timestamp/user/message`, chatEl);
                        }
                    } catch (e) {
                        console.error("[Twitch Adapter] 收集聊天時出錯:", e, chatEl);
                    }
                });

                console.log(`[Twitch Adapter] 最終收集到 ${newChats.length} 條聊天消息`);
                return newChats;
            },

            /**
             * 在 Twitch 页面模拟输入并发送聊天消息。
             * @param {string} message - 要发送的消息内容。
             * @returns {Promise<string>} 'success' | 'disabled' | 'not_found' | 'error'
             */
            sendChatMessage(message) {
                return new Promise((resolve) => {
                    if (typeof message !== 'string' || !message.trim()) {
                        console.error("Twitch适配器：消息为空或非法，无法发送。");
                        resolve('error');
                        return;
                    }

                    const target = document.querySelector('div[data-slate-node="element"]');
                    const sendButton = document.querySelector('button[data-a-target="chat-send-button"]');

                    if (!target) {
                        console.error("Twitch适配器：找不到聊天输入框 (div[data-slate-node='element'])。");
                        resolve('not_found');
                        return;
                    }
                    if (!sendButton) {
                        console.error("Twitch适配器：找不到发送按钮 (button[data-a-target='chat-send-button'])。");
                        resolve('not_found');
                        return;
                    }

                    if (sendButton.disabled) {
                        console.warn("Twitch适配器：发送按钮当前禁用（慢速模式或禁言）。");
                        resolve('disabled');
                        return;
                    }

                    try {
                        // 聚焦并选中输入框
                        target.focus();
                        const range = document.createRange();
                        range.selectNodeContents(target);
                        const selection = window.getSelection();
                        selection.removeAllRanges();
                        selection.addRange(range);

                        // 模拟粘贴 message 内容
                        const pasteEvent = new ClipboardEvent('paste', {
                            clipboardData: (() => {
                                const data = new DataTransfer();
                                data.setData('text/plain', message);
                                return data;
                            })(),
                            bubbles: true,
                            cancelable: true
                        });
                        target.dispatchEvent(pasteEvent);

                        // 等待一点时间，保证粘贴后的状态稳定
                        setTimeout(() => {
                            if (!sendButton.disabled) {
                                sendButton.click();
                                console.log(`✅ Twitch适配器：已成功发送消息 "${message}"`);
                                resolve('success');
                            } else {
                                console.warn("Twitch适配器：点击前按钮被禁用了。");
                                resolve('disabled');
                            }
                        }, 100); // 延迟 100ms 等待 paste 完成

                    } catch (err) {
                        console.error("Twitch适配器：发送聊天消息时发生错误：", err);
                        resolve('error');
                    }
                });
            }
            // twitch
        },
        // Add more platforms here if needed
    };

    /**
     * 检查当前 YouTube 页面是否正在直播。
     * 包含对标准直播徽章、首映指示器和时间显示类的检查。
     * @returns {boolean} 如果确定是直播则返回 true，否则（如 VOD、首映等待室等）返回 false。
     */
    function isYouTubeLiveNow() {

        // 原始的时间显示类检查 (备用)
        const timeDisplay = document.querySelector('.ytp-time-display');
        if (timeDisplay && timeDisplay.classList.contains('ytp-live')) {
            console.log("YT Live Check: 在时间显示上找到 'ytp-live' 类。");
            return true;
        }

        // 明确的首映指示器 (意味着还未直播或已结束)
        const premiereTextElement = document.querySelector('.ytp-paid-content-overlay-text, .ytp-title-subtext'); // 检查覆盖层和副标题
        if (premiereTextElement) {
            const premiereText = premiereTextElement.textContent?.toUpperCase();
            if (premiereText && (premiereText.includes('PREMIERE') || premiereText.includes('首播') || premiereText.includes('UPCOMING'))) {
                console.log("YT Live Check: 找到首映或即将播放指示器。");
                return false; // 如果是首映/即将播放，肯定不是直播
            }
        }

        // 特别查找控制栏中的红色 "LIVE" 圆点指示器
        const liveControlDot = document.querySelector('.ytp-chrome-controls .ytp-live-badge[disabled="false"] .ytp-menuitem-toggle-checkbox');
        if (liveControlDot) {
            console.log("YT Live Check: 找到直播控制圆点指示器。");
            return true;
        }

        console.log("YT Live Check: 未找到明确的直播指示器。假设是 VOD 或首映。");
        return false; // 如果没找到明确指示，则默认为 false
    }

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

    // --- 初始化 & 平台检测 ---
    let currentPlatformAdapter = null;
    let roomId = null; // 将 roomId 初始化为 null

    // 循环遍历适配器以找到匹配的
    for (const platformKey in platformAdapters) {
        const adapter = platformAdapters[platformKey];
        if (adapter.isApplicable()) {
            let shouldUseAdapter = true; // 假设可用，除非另有证明

            // **针对 YouTube 的特殊逻辑**
            if (platformKey === 'youtube') {
                // 确保 isYouTubeLiveNow 函数已经定义在前面
                if (typeof isYouTubeLiveNow !== 'function') {
                    console.error("AI Agent Error: isYouTubeLiveNow function is not defined yet!");
                    shouldUseAdapter = false; // 不能检查，就假设不可用
                } else if (!isYouTubeLiveNow()) { // 调用函数检查是否真的是直播
                    shouldUseAdapter = false; // 是 YouTube 但不是直播
                    console.log(`AI Agent (${adapter.platformName}): 检测到页面，但当前不是直播 (VOD/首映)。代理将不会激活。`);
                } else {
                    console.log(`AI Agent (${adapter.platformName}): 检测到直播流。继续激活。`);
                    // 是 YouTube 并且是直播，shouldUseAdapter 保持 true
                }
            }

            // 如果平台确认可用
            if (shouldUseAdapter) {
                currentPlatformAdapter = adapter;
                console.log(`AI Agent: 为平台激活: ${currentPlatformAdapter.platformName}`);
                break; // 找到可用适配器后停止搜索
            }
            // 如果是 YouTube VOD，shouldUseAdapter 为 false，循环继续（但不会找到其他匹配项）
        }
    }

    // 仅在找到有效的平台适配器时继续执行脚本的其余部分
    // --- 条件初始化 ---
    if (currentPlatformAdapter) {

        // 改成异步等待roomId成功
        waitForRoomId(currentPlatformAdapter, 10, 500).then(resolvedRoomId => { // <-- 把参数名改成 resolvedRoomId，避免混淆
            if (!resolvedRoomId) {
                console.error(`AI Agent (${currentPlatformAdapter.platformName}): 最终仍无法确定房间/视频 ID。代理可能无法正常工作。`);
                // 这里可以选择不加载UI，或者加载但禁用启动按钮，取决于你的需求
            } else {
                console.log(`AI Agent (${currentPlatformAdapter.platformName}): 为房间/视频 ID 初始化: ${resolvedRoomId}`);
                // !!! 添加这一行，把获取到的 ID 赋值给全局变量 !!!
                roomId = resolvedRoomId;
                console.log("全局 roomId 已更新为:", roomId); // 添加确认日志
            }

            // 无论是否成功拿到roomId，都继续加载UI
            createControlPanel(); // 创建控制面板
            observeVideoElement(); // 开始观察视频元素

        });

    } else {
        console.log("AI Agent: 未检测到适用的直播平台或未满足必要条件。脚本将不会注入 UI 或激活。");
        return;
    }

    /**
     * 辅助函数：等待平台适配器能拿到有效的 roomId
     * @param {object} adapter 当前平台适配器
     * @param {number} maxRetries 最大重试次数
     * @param {number} intervalMs 每次重试的间隔 (毫秒)
     * @returns {Promise<string|null>} 成功返回roomId，失败返回null
     */
    function waitForRoomId(adapter, maxRetries = 10, intervalMs = 500) {
        return new Promise(resolve => {
            let attempts = 0;

            const tryFetch = () => {
                const id = adapter.getRoomId();
                if (id) {
                    resolve(id);
                } else if (attempts >= maxRetries) {
                    resolve(null);
                } else {
                    attempts++;
                    console.warn(`YouTube Adapter: Retry finding channel username (${attempts}/${maxRetries})...`);
                    setTimeout(tryFetch, intervalMs);
                }
            };

            tryFetch();
        });
    }

    // --- 函数 ---

    /**
         * 创建控制面板 UI 并注入到页面中（使用 DOM 操作方法构建，兼容 Trusted Types）。
         */
    function createControlPanel() {
        console.log("AI Agent: 开始创建控制面板...");

        // --- 1. 注入样式 ---
        const style = document.createElement('style');
        style.textContent = `
    /* --- UI 面板样式 (省略，与之前相同) --- */
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
        display: flex; /* 为了让 tooltip icon 和文字在同一行 */
        align-items: center; /* 垂直居中 tooltip icon */
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
        cursor: pointer; /* Add cursor */
    }
    .volume-slider::-webkit-slider-thumb {
        appearance: none; /* Override default look */
        width: 16px;
        height: 16px;
        background: #4285f4;
        cursor: pointer;
        border-radius: 50%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }
    .volume-slider::-moz-range-thumb { /* Firefox thumb styles */
        width: 16px;
        height: 16px;
        background: #4285f4;
        cursor: pointer;
        border-radius: 50%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        border: none; /* Remove default border in FF */
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
        display: inline-flex; /* 更适合与文字混排 */
        align-items: center; /* 垂直居中 */
        margin-left: 4px; /* 与文字的间距 */
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
        line-height: 16px; /* 使 '!' 居中 */
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
        z-index: 10001; /* 确保在面板最上方 */
        bottom: 125%; /* 定位在图标上方 */
        left: 50%;
        transform: translateX(-50%);
        opacity: 0;
        transition: opacity 0.2s ease-in-out;
        white-space: pre-line; /* 让 \n 生效 */
        pointer-events: none; /* 避免 tooltip 自身阻挡鼠标事件 */
    }
    .tooltip-container:hover .tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    `;
        try {
            document.head.appendChild(style);
            console.log("AI Agent: 样式注入成功。");
        } catch (e) {
            console.error("AI Agent: 注入样式失败:", e);
            return; // 样式注入失败则不继续
        }

        // --- 2. 构建面板 DOM 结构 ---
        panel = document.createElement('div');
        panel.className = 'auto-chat-ai-panel';

        // -- 创建 Header --
        const header = document.createElement('div');
        header.className = 'panel-header';

        const titleSpan = document.createElement('span');
        titleSpan.className = 'panel-title';
        titleSpan.textContent = `${currentPlatformAdapter.platformName} Chat Agent`; // 使用适配器获取平台名称

        const menuSpan = document.createElement('span');
        menuSpan.className = 'panel-menu';
        menuSpan.textContent = '⋮'; // 使用 Unicode 垂直省略号字符
        menuSpan.title = 'Menu'; // 鼠标悬浮提示

        header.appendChild(titleSpan);
        header.appendChild(menuSpan);
        panel.appendChild(header);

        // -- 创建 Content --
        const contentDiv = document.createElement('div');
        contentDiv.className = 'panel-content';

        // 辅助函数：创建开关控件
        function createSwitchControl(id, labelText) {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'control-item';

            const labelSpan = document.createElement('span');
            labelSpan.className = 'control-label';
            labelSpan.textContent = labelText;

            const switchLabel = document.createElement('label');
            switchLabel.className = 'switch';

            const input = document.createElement('input');
            input.type = 'checkbox';
            input.id = id;

            const sliderSpan = document.createElement('span');
            sliderSpan.className = 'slider-switch';

            switchLabel.appendChild(input);
            switchLabel.appendChild(sliderSpan);

            itemDiv.appendChild(labelSpan);
            itemDiv.appendChild(switchLabel);
            return itemDiv;
        }

        // 辅助函数：创建带 Tooltip 的标签
        function createLabelWithTooltip(labelText, tooltipText) {
            const labelSpan = document.createElement('span');
            labelSpan.className = 'control-label';
            labelSpan.appendChild(document.createTextNode(labelText + ' ')); // 添加文本节点和空格

            const tooltipContainer = document.createElement('span');
            tooltipContainer.className = 'tooltip-container';

            const tooltipIcon = document.createElement('span');
            tooltipIcon.className = 'tooltip-icon';
            tooltipIcon.textContent = '!';

            const tooltipSpan = document.createElement('span');
            tooltipSpan.className = 'tooltip-text';
            tooltipSpan.textContent = tooltipText;

            tooltipContainer.appendChild(tooltipIcon);
            tooltipContainer.appendChild(tooltipSpan);
            labelSpan.appendChild(tooltipContainer);

            return labelSpan;
        }

        // -- 添加控件 --
        // 主控制开关
        contentDiv.appendChild(createSwitchControl('main-switch', 'Control')); // 使用中文标签

        // 聊天权限开关
        contentDiv.appendChild(createSwitchControl('chat-permission', 'Chat Permission')); // 使用中文标签

        // 静音开关 (带 Tooltip)
        const muteItemDiv = document.createElement('div');
        muteItemDiv.className = 'control-item';
        const muteLabel = createLabelWithTooltip('Mute', 'Does not affect AI Agent operation.');
        const muteSwitchLabel = document.createElement('label');
        muteSwitchLabel.className = 'switch';
        const muteInput = document.createElement('input');
        muteInput.type = 'checkbox';
        muteInput.id = 'mute-audio';
        const muteSliderSpan = document.createElement('span');
        muteSliderSpan.className = 'slider-switch';
        muteSwitchLabel.appendChild(muteInput);
        muteSwitchLabel.appendChild(muteSliderSpan);
        muteItemDiv.appendChild(muteLabel);
        muteItemDiv.appendChild(muteSwitchLabel);
        contentDiv.appendChild(muteItemDiv);

        // 音量滑块 (带 Tooltip)
        const volumeItemDiv = document.createElement('div');
        volumeItemDiv.className = 'control-item';
        volumeItemDiv.style.flexDirection = 'column';
        volumeItemDiv.style.alignItems = 'flex-start'; // 左对齐
        const volumeLabel = createLabelWithTooltip('Volume', 'Does not affect AI Agent operation.');
        volumeLabel.style.marginBottom = '5px'; // 添加下边距
        const volSlider = document.createElement('input');
        volSlider.type = 'range';
        volSlider.id = 'volume-slider';
        volSlider.className = 'volume-slider';
        volSlider.min = '0';
        volSlider.max = '100';
        volSlider.value = '50'; // 默认值
        volumeItemDiv.appendChild(volumeLabel);
        volumeItemDiv.appendChild(volSlider);
        contentDiv.appendChild(volumeItemDiv);

        // 运行/停止按钮
        runButton = document.createElement('button'); // 直接赋值给全局变量
        runButton.id = 'run-button';
        runButton.className = 'run-button';
        runButton.textContent = 'Start'; // 中文标签
        runButton.disabled = true; // 初始禁用
        contentDiv.appendChild(runButton);

        panel.appendChild(contentDiv);

        // --- 3. 将面板添加到页面 ---
        try {
            document.body.appendChild(panel);
            console.log("AI Agent: 控制面板成功添加到页面 Body。");
        } catch (e) {
            console.error("AI Agent: 添加面板到 Body 时出错:", e);
            // 失败时尝试移除可能部分添加的元素
            try { style.remove(); } catch (removeErr) { }
            try { panel.remove(); } catch (removeErr) { }
            return; // 添加失败则停止
        }

        // --- 4. 绑定元素引用和事件监听器 ---
        // Query elements *after* appending the panel
        const mainSwitch = panel.querySelector('#main-switch');
        const chatPermissionSwitch = panel.querySelector('#chat-permission');
        const muteAudioSwitch = panel.querySelector('#mute-audio');
        volumeSlider = panel.querySelector('#volume-slider'); // 赋值给全局变量
        // runButton 已经在上面创建时赋值

        // 检查元素是否都找到了
        if (!mainSwitch || !chatPermissionSwitch || !muteAudioSwitch || !volumeSlider || !runButton || !header) {
            console.error("AI Agent: 未能在面板中找到一个或多个必要的控制元素！");
            try { panel.remove(); } catch (removeErr) { } // 移除面板
            try { style.remove(); } catch (removeErr) { } // 移除样式
            return;
        }
        console.log("AI Agent: 成功获取所有控制元素引用。");

        // --- 添加事件监听 ---
        console.log("AI Agent: 开始绑定事件监听器...");
        mainSwitch.addEventListener('change', () => {
            isMainSwitchOn = mainSwitch.checked;
            console.log("主控制开关状态:", isMainSwitchOn);
            // 只有当主开关打开且视频元素存在时，才启用运行按钮
            const videoElement = currentPlatformAdapter?.findVideoElement();
            runButton.disabled = !(isMainSwitchOn && !!videoElement);
            console.log("运行按钮禁用状态:", runButton.disabled);
            if (!isMainSwitchOn && isAgentRunning) {
                console.log("主控制关闭，停止代理...");
                stopAgent();
            }
        });

        chatPermissionSwitch.addEventListener('change', () => {
            isChatPermissionGranted = chatPermissionSwitch.checked;
            console.log("聊天权限开关状态:", isChatPermissionGranted);
            if (!isChatPermissionGranted) {
                console.log("聊天权限关闭，清空待发送队列。");
                chatQueue = []; // 如果撤销权限，清空队列
            }
        });

        muteAudioSwitch.addEventListener('change', () => {
            isMuted = muteAudioSwitch.checked;
            console.log("静音开关状态:", isMuted);
            updateGain();
        });

        volumeSlider.addEventListener('input', () => {
            // 实时更新音量，不必每次都 log
            if (!isMuted) updateGain();
        });
        // 可选: 添加 change 事件监听器，在用户松开滑块时 log 一次最终值
        volumeSlider.addEventListener('change', () => {
            console.log("音量滑块最终值:", volumeSlider.value);
            if (!isMuted) updateGain(); // 确保最终值被设置
        });

        runButton.addEventListener('click', () => {
            if (isAgentRunning) {
                console.log("点击停止按钮");
                stopAgent();
            } else if (isMainSwitchOn) {
                console.log("点击启动按钮");
                startAgent();
            } else {
                console.log("点击启动按钮，但主开关未打开");
            }
        });
        console.log("AI Agent: 事件监听器绑定完成。");

        // --- 拖动逻辑 ---
        console.log("AI Agent: 开始绑定拖动逻辑...");
        let isDragging = false, startX = 0, startY = 0, origX = 0, origY = 0;
        header.addEventListener('mousedown', e => {
            if (e.button !== 0) return; // 只响应左键
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            // 使用 getComputedStyle 获取准确的初始位置
            const computedStyle = window.getComputedStyle(panel);
            origX = parseFloat(computedStyle.left);
            origY = parseFloat(computedStyle.top);
            // 如果解析失败（例如初始值是 'auto'），使用 getBoundingClientRect 作为备选
            if (isNaN(origX) || isNaN(origY)) {
                const rect = panel.getBoundingClientRect();
                origX = rect.left;
                origY = rect.top;
                console.warn("AI Agent Drag: 无法从 computedStyle 解析 'left'/'top'，使用 getBoundingClientRect 作为备选。");
            }

            panel.style.transition = 'none'; // 拖动时取消过渡效果
            document.body.style.userSelect = 'none'; // 拖动时禁止选择文本
            header.style.cursor = 'grabbing'; // 更改鼠标样式
            console.log("开始拖动面板");
        });

        document.addEventListener('mousemove', e => {
            if (!isDragging) return;
            // 计算新位置并更新样式
            panel.style.left = origX + (e.clientX - startX) + 'px';
            panel.style.top = origY + (e.clientY - startY) + 'px';
        });

        document.addEventListener('mouseup', e => {
            if (e.button !== 0 || !isDragging) return; // 只处理左键释放且正在拖动的情况
            isDragging = false;
            panel.style.transition = ''; // 恢复过渡效果（如果之前有的话）
            document.body.style.userSelect = ''; // 恢复文本选择
            header.style.cursor = 'grab'; // 恢复鼠标样式
            console.log("结束拖动面板");
        });
        console.log("AI Agent: 拖动逻辑绑定完成。");

        console.log("AI Agent: 控制面板 UI 创建和初始化完成！");
    } // createControlPanel 函数结束

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
        // Ensure Room ID is valid before starting
        if (!roomId) {
            console.error(`AI Agent (${currentPlatformAdapter.platformName}): Cannot start, invalid Room/Video ID.`);
            alert("错误：无法获取房间/视频 ID，请检查页面是否为有效直播/视频页。");
            return;
        }
        if (!currentPlatformAdapter.findVideoElement()) {
            console.error(`AI Agent (${currentPlatformAdapter.platformName}): Cannot start, video element not found.`);
            alert("错误：未找到视频元素，请确保直播/视频已加载。");
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
            alert("错误：无法访问视频音频。请确保直播/视频正在播放且浏览器允许访问。");
            // 保持按钮和开关的状态（用户需要修复问题）
            isAgentRunning = false; // 确保运行状态为 false
            runButton.textContent = 'Start'; // 中文
            runButton.classList.remove('running');
            // Make button available if main switch is on, even if audio failed, so user can retry
            runButton.disabled = !isMainSwitchOn;
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
        // 确保主开关打开且视频元素存在时，按钮是可用的
        runButton.disabled = !(isMainSwitchOn && !!currentPlatformAdapter.findVideoElement());

        console.log("AI Agent stopped.");
    }

    /**
 * 设置 MutationObserver 以检测视频元素何时添加到 DOM 中。
 */
    function observeVideoElement() {
        const targetNode = document.body;
        const config = { childList: true, subtree: true };

        const observer = new MutationObserver((mutationsList, obs) => {
            // Use platform adapter to find video element
            const videoElement = currentPlatformAdapter.findVideoElement();
            if (videoElement) {
                console.log(`AI Agent (${currentPlatformAdapter.platformName}): Video element detected.`);
                obs.disconnect(); // 一旦找到就停止观察
                // 视频元素找到后，如果主开关是开的，则自动启用运行按钮
                if (isMainSwitchOn && runButton) {
                    runButton.disabled = false;
                }
                // Optional: Re-initialize audio if needed, e.g., if video element was replaced
                // initializeAudio();
            }
        });

        // 初始检查，以防元素已经存在
        if (currentPlatformAdapter.findVideoElement()) {
            console.log(`AI Agent (${currentPlatformAdapter.platformName}): Video element already present.`);
            if (isMainSwitchOn && runButton) {
                runButton.disabled = false;
            }
        } else {
            console.log(`AI Agent (${currentPlatformAdapter.platformName}): Observing for video element...`);
            observer.observe(targetNode, config);
            // Keep run button disabled until video is found
            if (runButton) runButton.disabled = true;
        }
    }

    /**
     * 初始化 AudioContext 并连接视频元素源。
     * @returns {boolean} 如果初始化成功则为 true，否则为 false。
     */
    function initializeAudio() {
        // Use platform adapter to find video element
        const videoElement = currentPlatformAdapter.findVideoElement();
        if (!videoElement) {
            console.error("Cannot initialize audio: Video element not found by adapter.");
            return false;
        }
        // 确保视频有音轨（readyState 考虑改为 HAVE_METADATA 或更高）
        if (videoElement.readyState < 1) { // HAVE_NOTHING or HAVE_METADATA is often enough to get tracks
            console.warn(`Video element readyState (${videoElement.readyState}) might be too low. Audio capture could fail if tracks are not ready.`);
            // Try connecting anyway, browsers might handle it.
        }
        // Check for actual audio tracks
        const audioTracks = videoElement.captureStream ? videoElement.captureStream().getAudioTracks() : (videoElement.mozCaptureStream ? videoElement.mozCaptureStream().getAudioTracks() : []);
        if (audioTracks.length === 0 && videoElement.readyState < 3) { // HAVE_CURRENT_DATA or more likely needed for source node
            console.warn("Video element does not seem to have audio tracks yet or is not playing.");
            // Proceed, but it might naturally fail later if no audio comes through.
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
                    // This might be critical, audio won't work.
                });
            }

            // 仅当节点不存在时才创建它们
            if (!destination) {
                destination = audioContext.createMediaStreamDestination(); // 创建录音目标节点
                console.log("MediaStreamAudioDestinationNode created.");
            }
            // 每次都尝试重新连接源，以防视频元素被替换
            if (mediaElementSource) {
                try {
                    mediaElementSource.disconnect(); // 断开旧连接
                } catch (e) {
                    console.warn("Minor error disconnecting old media element source:", e);
                }
            }
            // Error handling specifically for createMediaElementSource
            try {
                mediaElementSource = audioContext.createMediaElementSource(videoElement); // 从视频创建源节点
                console.log("MediaElementAudioSourceNode created/reconnected.");
            } catch (sourceError) {
                console.error("Error creating MediaElementAudioSourceNode:", sourceError);
                // This usually happens if the element doesn't have audio or isn't properly loaded
                if (videoElement.src) {
                    console.error("Video source:", videoElement.src); // Log src for debugging
                } else {
                    console.error("Video element has no 'src' attribute.");
                }
                // Attempt to use captureStream as a fallback if supported
                if (videoElement.captureStream && audioTracks.length > 0) {
                    console.log("Attempting fallback using captureStream().");
                    const mediaStream = videoElement.captureStream();
                    mediaElementSource = audioContext.createMediaStreamSource(mediaStream);
                    console.log("Fallback MediaStreamSource created.");

                } else {
                    throw sourceError; // Re-throw if fallback not possible
                }
            }

            if (!gainNode) {
                gainNode = audioContext.createGain(); // 创建音量控制节点
                console.log("GainNode created.");
            }

            // 设置音频处理管线:
            // video source -> 音量控制 -> 录音目标 (用于录制)
            // video source -> 音量控制 -> 实际输出 (用于收听)
            mediaElementSource.connect(gainNode);
            gainNode.connect(destination); // 连接音量节点到录音目标
            gainNode.connect(audioContext.destination); // 连接音量节点到实际扬声器

            console.log("Audio nodes connected.");
            updateGain(); // 根据 UI 设置初始音量
            return true;
        } catch (error) {
            console.error("Error initializing audio context or nodes:", error);
            // 清理可能部分创建的元素
            if (gainNode) { try { gainNode.disconnect(); } catch (e) { } }
            if (mediaElementSource) { try { mediaElementSource.disconnect(); } catch (e) { } }
            // Do not null out audioContext, maybe it can be resumed/reused
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
        if (gainNode && audioContext && audioContext.state === 'running') { // Only update if context is running
            try {
                const volumeValue = parseFloat(volumeSlider.value) / 100;
                const targetVolume = isMuted ? 0 : volumeValue;
                // Use setTargetAtTime for smoother volume changes
                gainNode.gain.setTargetAtTime(targetVolume, audioContext.currentTime, 0.015); // Target in ~15ms
                // console.log(`Gain target set to: ${targetVolume}`);
            } catch (e) {
                console.error("Error setting gain value:", e);
                // Fallback to immediate set if smooth transition fails
                try {
                    const volumeValue = parseFloat(volumeSlider.value) / 100;
                    gainNode.gain.value = isMuted ? 0 : volumeValue;
                } catch (e2) {
                    console.error("Fallback gain setting also failed:", e2);
                }
            }
        } else if (gainNode && audioContext && audioContext.state !== 'running') {
            // console.log("AudioContext not running, skipping gain update.");
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
        if (!destination || !destination.stream) { // Check stream existence too
            console.error("Cannot start recording cycle: Audio destination or stream not initialized.");
            stopAgent(); // Stop if audio setup is bad
            return;
        }

        console.log('Starting recording cycle...');

        // 确保创建录制器
        const options = { mimeType: 'audio/webm;codecs=opus' };
        try {
            // Check if MediaRecorder is available and supports the MIME type
            if (typeof MediaRecorder === 'undefined') {
                throw new Error("MediaRecorder API is not supported by this browser.");
            }
            if (!MediaRecorder.isTypeSupported(options.mimeType)) {
                console.warn(`MIME type ${options.mimeType} not supported. Trying default.`);
                // Try without options or with a fallback like audio/ogg
                options.mimeType = 'audio/ogg;codecs=opus'; // Another common option
                if (!MediaRecorder.isTypeSupported(options.mimeType)) {
                    console.warn(`MIME type ${options.mimeType} also not supported. Trying browser default.`);
                    delete options.mimeType; // Let the browser choose
                }
            }
            // Ensure stream has active audio tracks
            if (destination.stream.getAudioTracks().length === 0 || !destination.stream.active) {
                throw new Error("Audio destination stream has no active audio tracks.");
            }

            mediaRecorder1 = new MediaRecorder(destination.stream, options);
            mediaRecorder2 = new MediaRecorder(destination.stream, options);
            console.log(`MediaRecorders created${options.mimeType ? ' with type: ' + options.mimeType : ' with default type'}.`);
        } catch (e) {
            console.error("Error creating MediaRecorder:", e);
            alert(`错误：无法创建音频录制器。浏览器可能不支持所需功能或音频流无效。\n${e.message}`);
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
            if (event.data.size > 0) {
                chunks.push(event.data); // 将数据块存入数组
            }
        };

        recorder.onstart = () => {
            console.log(`${label} started recording.`);
            recordingStartTimestamp = Date.now(); // 标记此块的开始时间
            chunks.length = 0; // 清空块数组以用于新的录制段
        };

        recorder.onstop = async () => {
            console.log(`${label} stopped recording.`);
            recordingEndTimestamp = Date.now();

            // 标记对应的录制器为非活动
            if (label === 'Recorder 1') isRecorder1Active = false;
            else isRecorder2Active = false;

            // 检查代理运行状态
            const shouldContinue = isAgentRunning;

            if (chunks.length > 0) {
                const audioBlob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }); // 使用录制器实际的 mimetype
                if (audioBlob.size < 2048) { // Increase threshold slightly for header data etc.
                    console.warn(`${label}: Blob size is very small (${audioBlob.size} bytes), skipping send.`);
                } else {
                    // 使用适配器收集聊天消息
                    const chats = currentPlatformAdapter.collectChatMessages(recordingStartTimestamp, recordingEndTimestamp);
                    const screenshotBlob = await captureScreenshot(); // 捕获屏幕截图 (uses adapter's findVideoElement)
                    sendDataToServer(audioBlob, chats, screenshotBlob); // 发送数据
                }
                chunks.length = 0; // 清空块数组
            } else {
                console.log(`${label}: No audio data recorded in this interval.`);
                // Even if no audio, maybe send chat/screenshot if needed?
                // if (!isSending) { // Only if not currently sending
                //    const chats = currentPlatformAdapter.collectChatMessages(recordingStartTimestamp, recordingEndTimestamp);
                //    const screenshotBlob = await captureScreenshot()
                //    if (chats.length > 0 || screenshotBlob) {
                //        sendDataToServer(null, chats, screenshotBlob); // Send without audio
                //    }
                // }
            }

            // 如果代理应该继续运行，并且是时候切换了
            if (shouldContinue) {
                // Only start the *next* recorder if *this* one just stopped and the other is *not* active
                const otherIsActive = (label === 'Recorder 1') ? isRecorder2Active : isRecorder1Active;
                if (!otherIsActive) {
                    startSpecificRecorder(nextRecorder);
                } else {
                    // This case might happen if stop was called manually while the other was schedule to start
                    console.log(`Waiting for the other recorder (${otherIsActive ? (label === 'Recorder 1' ? 'Recorder 2' : 'Recorder 1') : 'N/A'}) to potentially stop before starting next.`);
                }
            } else {
                console.log("Agent run state is false, not starting next recorder.");
                isRecorder1Active = false; // Ensure both flags are false on final stop
                isRecorder2Active = false;
            }
        };

        recorder.onerror = (event) => {
            let errorMsg = "Unknown recording error";
            if (event.error) {
                errorMsg = `${event.error.name}: ${event.error.message}`;
            }
            console.error(`${label} error:`, errorMsg, event);
            // 标记对应的录制器为非活动
            if (label === 'Recorder 1') isRecorder1Active = false;
            else isRecorder2Active = false;

            alert(`录制器 ${label} 发生错误: ${errorMsg}\n请检查控制台并可能需要重启代理。`);
            stopAgent(); // 在错误时停止整个代理
        };
    }

    /**
     * 启动特定的 MediaRecorder 并设置其超时。
     * 确保只有在代理运行时才启动，并更新活动标志。
     * @param {MediaRecorder} recorderToStart - 要启动的录制器实例。
     */
    function startSpecificRecorder(recorderToStart) {
        if (!isAgentRunning) {
            console.log("Preventing recorder start because Agent run state is false.");
            isRecorder1Active = false; // 确保标志重置
            isRecorder2Active = false;
            return;
        }
        // 检查录制器是否已经是活动状态或非 'inactive' 状态
        const label = recorderToStart === mediaRecorder1 ? 'Recorder 1' : 'Recorder 2';
        if ((label === 'Recorder 1' && isRecorder1Active) ||
            (label === 'Recorder 2' && isRecorder2Active) ||
            recorderToStart.state !== 'inactive') {
            console.warn(`Attempted to start ${label} which is already active or not inactive (state: ${recorderToStart.state}).`);
            return;
        }

        try {
            // Check stream status again right before starting
            if (!destination || !destination.stream || !destination.stream.active) {
                throw new Error(`Cannot start ${label}: Destination stream is not active.`);
            }
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
                // Also check if the agent is still supposed to be running
                if (isAgentRunning && recorderToStart && recorderToStart.state === 'recording') {
                    console.log(`Timeout reached for ${label}, stopping...`);
                    try {
                        // recorderToStart.requestData(); // Request data just before stopping? Might not be needed with chunking.
                        recorderToStart.stop(); // 停止录制（将触发 onstop）
                    } catch (stopError) {
                        console.error(`Error during ${label}.stop() via timeout:`, stopError);
                        // 手动标记为非活动并停止代理
                        if (label === 'Recorder 1') isRecorder1Active = false; else isRecorder2Active = false;
                        stopAgent();
                    }
                } else {
                    // console.log(`${label} was already stopped, inactive, or agent stopped when timeout triggered.`);
                    // Ensure flags are false if recorder isn't active
                    if (recorderToStart.state !== 'recording') {
                        if (label === 'Recorder 1') isRecorder1Active = false; else isRecorder2Active = false;
                    }
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
            console.error(`Error starting ${label}:`, startError);
            alert(`启动音频录制器 ${label} 失败: ${startError.message}`);
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

        // 停止录制器 - 确保检查状态避免错误
        [mediaRecorder1, mediaRecorder2].forEach((recorder, index) => {
            const label = `Recorder ${index + 1}`;
            if (recorder && recorder.state === 'recording') {
                try {
                    console.log(`Force stopping ${label} due to agent stop command.`);
                    recorder.stop(); // onstop will handle logic based on `isAgentRunning = false`
                } catch (e) {
                    console.warn(`Error force stopping ${label}:`, e);
                    // Manually set flags just in case onstop doesn't fire correctly after error
                    if (index === 0) isRecorder1Active = false; else isRecorder2Active = false;
                }
            } else if (recorder && recorder.state === 'paused') {
                // This state shouldn't normally be used, but handle it
                try {
                    console.log(`Force stopping paused ${label}.`);
                    recorder.stop();
                } catch (e) { console.warn(`Error stopping paused ${label}:`, e); }
                if (index === 0) isRecorder1Active = false; else isRecorder2Active = false;
            } else {
                // Recorder is inactive or null
                if (index === 0) isRecorder1Active = false; else isRecorder2Active = false;
            }
        });

        // 额外确保标志被清除 (以防 onstop 逻辑出问题)
        isRecorder1Active = false;
        isRecorder2Active = false;

        // 清空数据块和累积状态
        chunks1 = [];
        chunks2 = [];
        accumulatedChunks = [];
        isAccumulating = false;
        // isSending 状态由 XHR 回调处理，不清

        // 可以选择性清理 AudioContext 资源，但这可能需要重新初始化
        // if (audioContext && audioContext.state !== 'closed') {
        //     audioContext.close().then(() => console.log("AudioContext closed.")).catch(e => console.warn("Error closing AudioContext:", e));
        //     audioContext = null;
        // }
        // if (destination) { destination.disconnect(); destination = null; }
        // if (gainNode) { gainNode.disconnect(); gainNode = null; }
        // if (mediaElementSource) { mediaElementSource.disconnect(); mediaElementSource = null; }
        // mediaRecorder1 = null; // Release recorder instances
        // mediaRecorder2 = null;

        console.log("Recording cycle fully stopped and resources potentially cleared.");
    }

    /**
     * 捕获当前视频帧的屏幕截图。
     * @returns {Promise<Blob|null>} 一个 Promise，解析为截图 Blob (JPEG) 或在错误时为 null。
     */
    async function captureScreenshot() {
        // 使用适配器获取视频元素
        const videoElement = currentPlatformAdapter.findVideoElement();
        if (!videoElement) {
            console.warn('Screenshot: Video element not found by adapter.');
            return null;
        }
        // Check if video has dimensions and data
        if (videoElement.readyState < 1 || videoElement.videoWidth === 0 || videoElement.videoHeight === 0) {
            console.warn(`Screenshot: Video element not ready (readyState: ${videoElement.readyState}, width: ${videoElement.videoWidth}, height: ${videoElement.videoHeight}).`);
            return null;
        }

        const canvas = document.createElement('canvas');
        // Adjust desired dimensions based on video aspect ratio to avoid distortion
        const aspectRatio = videoElement.videoWidth / videoElement.videoHeight;
        let targetWidth = SCREENSHOT_WIDTH;
        let targetHeight = SCREENSHOT_HEIGHT;

        if (aspectRatio > (SCREENSHOT_WIDTH / SCREENSHOT_HEIGHT)) {
            // Video is wider than target aspect ratio, limited by width
            targetHeight = Math.round(SCREENSHOT_WIDTH / aspectRatio);
        } else {
            // Video is taller or equal aspect ratio, limited by height
            targetWidth = Math.round(SCREENSHOT_HEIGHT * aspectRatio);
        }

        canvas.width = targetWidth;
        canvas.height = targetHeight;

        try {
            const ctx = canvas.getContext('2d');
            if (!ctx) {
                throw new Error("Could not get 2D context from canvas.");
            }
            // Clear canvas (might be needed if reusing canvases, not strictly necessary here)
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            // Draw the video frame onto the canvas
            ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

            // Check if canvas is blank (can happen with protected content or errors)
            // This check is not foolproof but can catch some issues.
            // if (isCanvasBlank(canvas)) {
            //     console.warn("Screenshot: Canvas appears blank after drawing video. Might be protected content.");
            //     return null;
            // }

            // Return a promise that resolves with the blob
            return new Promise((resolve) => {
                canvas.toBlob((blob) => {
                    if (!blob) {
                        console.error("Screenshot: canvas.toBlob returned null. Canvas might be tainted or too large.");
                    } else {
                        // console.log(`Screenshot captured: ${blob.size} bytes, dimensions: ${canvas.width}x${canvas.height}`);
                    }
                    resolve(blob); //
                }, 'image/jpeg', SCREENSHOT_QUALITY); // Specify format and quality
            });
        } catch (error) {
            console.error('Error capturing screenshot:', error);
            if (error.name === 'SecurityError') {
                console.error("Could not capture screenshot due to cross-origin restrictions (video source might be from another domain).");
            }
            return null; // Return null on any error
        }
    }

    // Helper function to check if canvas is blank (simple version)
    // function isCanvasBlank(canvas) {
    //     const ctx = canvas.getContext('2d');
    //     const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    //     return !imageData.data.some(channel => channel !== 0);
    // }

    /**
     * 解析后端返回的 JSON，提取我们关注的字段
     * @param {object} resp 后端返回的 JSON 对象
     * @returns {{
    *   messages: string[],
    *   think: string|null,
    *   continues: number|null,
    *   notepadNotes: string[],
    *   contextCleared: boolean,
    *   youdao: string|null,
    *   whisper: string|null,
    *   imageUrl: string|null,
    *   raw: string
    * }}
    */
    function parseServerResponse(resp) {
        return {
            messages: Array.isArray(resp.chat_messages)
                ? resp.chat_messages.map(item => item.content).filter(c => typeof c === 'string' && c.trim())
                : [],
            think: resp.internal_think || null,
            continues: resp.continues != null ? resp.continues : null,
            notepadNotes: Array.isArray(resp.new_notepad) ? resp.new_notepad : [],
            contextCleared: !!resp.context_cleared,
            youdao: resp.recognized_text_youdao || null,
            whisper: resp.recognized_text_whisper || null,
            imageUrl: resp.image_url || null,
            raw: resp.LLM_response_raw || ''
        };
    }

    /**
     * 将音频、弹幕消息和截图发送到后端 API。
     * 处理累积逻辑。
     * @param {Blob|null} audioBlob - 录制的音频数据 (可以是 null).
     * @param {Array<object>} chats - 收集到的弹幕消息对象数组。
     * @param {Blob|null} screenshotBlob - 捕获的屏幕截图 blob，或 null。
     */
    function sendDataToServer(audioBlob, chats, screenshotBlob) {
        // Ensure we have *something* to send
        if ((!audioBlob || audioBlob.size === 0) && chats.length === 0 && !screenshotBlob) {
            console.log("No valid data (audio, chat, or screenshot) to send.");
            return;
        }

        // 处理累积逻辑 (只累积音频)
        if (isSending) {
            console.log('Previous request in progress. Accumulating audio chunk (if present)...');
            if (audioBlob && audioBlob.size > 0) {
                if (!isAccumulating) {
                    accumulatedChunks = [audioBlob]; // 开始新的累积
                    isAccumulating = true;
                } else {
                    accumulatedChunks.push(audioBlob); // 添加到现有累积中
                }
            }
            // 简单起见，不累积弹幕和截图 for now
            return;
        }

        // 合并累积的块
        let finalAudioBlob = audioBlob;
        if (isAccumulating && accumulatedChunks.length > 0) {
            console.log(`Merging ${accumulatedChunks.length} accumulated audio chunks with the current one (if any).`);
            // If current audioBlob exists, add it to the front before merging
            const chunksToMerge = audioBlob ? [audioBlob, ...accumulatedChunks] : [...accumulatedChunks];
            if (chunksToMerge.length > 0) {
                finalAudioBlob = new Blob(chunksToMerge, { type: chunksToMerge[0].type }); // Use type of first chunk
                console.log(`Merged audio blob size: ${finalAudioBlob.size} bytes`);
            } else {
                finalAudioBlob = null; // No audio after all
            }
            accumulatedChunks = []; // Clear accumulated
            isAccumulating = false;
        }

        // --- 准备并发送数据 ---
        isSending = true; // 设置发送锁
        const dataSize = finalAudioBlob ? finalAudioBlob.size : 0;
        const screenshotSize = screenshotBlob ? screenshotBlob.size : 0;
        console.log(`Preparing to send data. Audio: ${dataSize} bytes, Chats: ${chats.length}, Screenshot: ${screenshotSize} bytes.`);

        const formData = new FormData();
        // Append data only if it exists and is valid
        if (finalAudioBlob && finalAudioBlob.size > 0) {
            formData.append('audio', finalAudioBlob, `audio_${Date.now()}.webm`);
        }
        // Append chats even if empty, backend might expect the field
        formData.append('chats', JSON.stringify(chats));
        formData.append('roomId', roomId || 'unknown'); // Send ID or fallback
        formData.append('platform', currentPlatformAdapter.platformName); // Send platform identifier

        if (screenshotBlob && screenshotBlob.size > 0) {
            const timestampStr = new Date().toISOString().replace(/[:.]/g, "-");
            const screenshotFilename = `${roomId || 'unknown'}_${timestampStr}.jpg`;
            formData.append('screenshot', screenshotBlob, screenshotFilename);
        }
        // Add recording interval timestamps
        formData.append('startTimestamp', recordingStartTimestamp.toString());
        formData.append('endTimestamp', recordingEndTimestamp.toString());

        // --- 使用 XMLHttpRequest 发送 ---
        const xhr = new XMLHttpRequest();
        xhr.open('POST', API_ENDPOINT, true);
        xhr.timeout = 90000; // Increase timeout to 90 seconds for potentially larger uploads / slower AI processing

        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) { // 请求完成
                console.log(`[XHR] Upload complete. Status: ${xhr.status}`);
                isSending = false; // **释放锁**

                if (xhr.status >= 200 && xhr.status < 300) { // Success range
                    try {
                        const resp = JSON.parse(xhr.responseText);
                        console.log('Server Response:', resp);
                        if (resp.status === 'success') {
                            console.log('Server processed data successfully.');

                            // —— 新：统一解析后端结构 ——
                            const parsed = parseServerResponse(resp);

                            console.log('> Youdao STT    :', parsed.youdao);
                            console.log('> Whisper STT   :', parsed.whisper);
                            console.log('> Internal Think:', parsed.think);
                            console.log('> Continues     :', parsed.continues);
                            console.log('> Notepad Notes :', parsed.notepadNotes);
                            console.log('> Image URL     :', parsed.imageUrl);

                            // —— 处理弹幕消息 —— 
                            if (parsed.messages.length > 0) {
                                if (isChatPermissionGranted) {
                                    console.log(`Queueing ${parsed.messages.length} message(s) from AI.`);
                                    parsed.messages.forEach(msgContent => {
                                        const parts = splitMessage(msgContent);
                                        chatQueue.push(...parts);
                                    });
                                    processChatQueue();
                                } else {
                                    console.log("AI provided messages, but chat permission is OFF. Messages discarded.");
                                }
                            } else {
                                console.log('No actionable chat messages received from AI response.');
                            }

                        } else {
                            console.error(
                                'Server returned an application error:',
                                resp.message || "No error message provided.",
                                resp
                            );
                        }
                    } catch (e) {
                        console.error('Failed to parse JSON response:', e);
                        console.error('Raw Response Text:', xhr.responseText);
                    }
                } else {
                    // HTTP 错误
                    console.error(`Failed to send data. HTTP Status: ${xhr.status} ${xhr.statusText}`);
                    console.error('Response Text:', xhr.responseText);
                }

                // —— 处理累积的音频块 —— 
                if (isAccumulating && accumulatedChunks.length > 0) {
                    console.log("Processing accumulated chunks immediately after send completion.");
                    const nextBlob = accumulatedChunks.shift();
                    if (accumulatedChunks.length === 0) isAccumulating = false;

                    if (nextBlob) {
                        console.warn("Sending accumulated audio chunk without fresh chat/screenshot context.");
                        sendDataToServer(nextBlob, [], null);
                    } else {
                        console.warn("Accumulated chunks array was manipulated unexpectedly.");
                        isAccumulating = false;
                    }
                }
            }
        };

        xhr.onerror = function () { // 网络错误
            console.error('[XHR] Network error occurred during upload.');
            isSending = false; // **释放锁**
            // Handle accumulated chunks after network error
            if (isAccumulating && accumulatedChunks.length > 0) {
                console.log("Processing accumulated chunks after network error.");
                const nextBlob = accumulatedChunks.shift();
                if (accumulatedChunks.length === 0) isAccumulating = false;
                if (nextBlob) {
                    console.warn("Sending accumulated audio chunk without fresh chat/screenshot context.");
                    sendDataToServer(nextBlob, [], null);
                } else {
                    console.warn("Accumulated chunks array was manipulated unexpectedly.");
                    isAccumulating = false;
                }
            }
        };

        xhr.ontimeout = function () { // 请求超时
            console.error('[XHR] Request timed out.');
            isSending = false; // **释放锁**
            // Handle accumulated chunks after timeout
            if (isAccumulating && accumulatedChunks.length > 0) {
                console.log("Processing accumulated chunks after timeout.");
                const nextBlob = accumulatedChunks.shift();
                if (accumulatedChunks.length === 0) isAccumulating = false;
                if (nextBlob) {
                    console.warn("Sending accumulated audio chunk without fresh chat/screenshot context.");
                    sendDataToServer(nextBlob, [], null);
                } else {
                    console.warn("Accumulated chunks array was manipulated unexpectedly.");
                    isAccumulating = false;
                }
            }
        };

        try {
            xhr.send(formData); // 发送数据
            console.log('Data send request initiated.');
        } catch (sendError) {
            console.error("[XHR] Error initiating send:", sendError);
            isSending = false; // Ensure lock is released if send fails immediately
            // Handle accumulation again? Or just log and stop?
            isAccumulating = false; // Safer to just clear accumulation state on send error
            accumulatedChunks = [];
        }
    }

    /**
     * 将长消息拆分成适合弹幕发送的短片段。
     * 支持平台适配和强制覆盖切分长度。
     * @param {string} message - 原始长消息
     * @returns {string[]}     - 拆分后的弹幕数组
     */
    function splitMessage(message) {
        const parts = [];
        if (!message) return parts;

        // 动态决定切分长度
        let currentMaxChatLength = MAX_CHAT_LENGTH; // 默认

        if (FORCE_CHAT_LENGTH > 0) {
            currentMaxChatLength = FORCE_CHAT_LENGTH;
        } else if (currentPlatformAdapter?.platformName === 'YouTube') {
            currentMaxChatLength = 100; // YouTube专用
        } else if (currentPlatformAdapter?.platformName === 'Bilibili') {
            currentMaxChatLength = 20; // Bilibili专用（其实就是MAX_CHAT_LENGTH）
        }

        // 若整体就不超长，直接返回
        if (message.length <= currentMaxChatLength) return [message];

        // 智能分割，优先按标点和空格
        const separators = /[\s,.!?，。！？]+/g;
        let lastIndex = 0;
        let currentPart = '';

        let match;
        while ((match = separators.exec(message)) !== null) {
            const chunk = message.substring(lastIndex, match.index).trim();
            const sep = match[0];

            if (chunk) {
                const potentialPart = currentPart ? `${currentPart} ${chunk}` : chunk;
                if (potentialPart.length <= currentMaxChatLength) {
                    currentPart = potentialPart;
                } else {
                    if (currentPart) parts.push(currentPart);
                    if (chunk.length <= currentMaxChatLength) {
                        currentPart = chunk;
                    } else {
                        for (let i = 0; i < chunk.length; i += currentMaxChatLength) {
                            parts.push(chunk.slice(i, i + currentMaxChatLength));
                        }
                        currentPart = '';
                    }
                }
            }
            lastIndex = match.index + sep.length;
        }

        // 处理最后一段
        const finalChunk = message.substring(lastIndex).trim();
        if (finalChunk) {
            const potentialPart = currentPart ? `${currentPart} ${finalChunk}` : finalChunk;
            if (potentialPart.length <= currentMaxChatLength) {
                currentPart = potentialPart;
                if (currentPart) parts.push(currentPart);
            } else {
                if (currentPart) parts.push(currentPart);
                for (let i = 0; i < finalChunk.length; i += currentMaxChatLength) {
                    parts.push(finalChunk.slice(i, i + currentMaxChatLength));
                }
            }
        } else if (currentPart) {
            parts.push(currentPart);
        }

        // 如果仍然为空（极端情况），硬切
        if (parts.length === 0 && message.length > 0) {
            for (let i = 0; i < message.length; i += currentMaxChatLength) {
                parts.push(message.slice(i, i + currentMaxChatLength));
            }
        }

        return parts;
    }

    let isProcessingQueue = false; // Lock to prevent concurrent processing runs
    /**
     * 处理弹幕队列，一次发送一条消息，并带有延迟。
     */
    async function processChatQueue() {
        if (isProcessingQueue) {
            // console.log("Chat queue processing already in progress.");
            return;
        }
        if (chatQueue.length === 0) {
            // console.log("Chat queue is empty.");
            isProcessingQueue = false; // Release lock if queue becomes empty
            return;
        }
        // 在发送前再次检查权限 and agent running status
        if (!isChatPermissionGranted || !isAgentRunning) {
            console.log(`Chat permission (${isChatPermissionGranted}) or agent running (${isAgentRunning}) is false. Clearing remaining queue.`);
            chatQueue = [];
            isProcessingQueue = false; // Release lock
            return;
        }

        isProcessingQueue = true; // Acquire lock

        const message = chatQueue.shift(); // 从队列前面取出下一条消息
        console.log(`Processing chat queue. Remaining: ${chatQueue.length}. Next message: "${message}"`);

        try {
            // Use the platform adapter to send the message
            const status = await currentPlatformAdapter.sendChatMessage(message); // Adapter returns status

            switch (status) {
                case 'success':
                    console.log(`Successfully sent chat (via adapter): "${message}"`);
                    // Schedule next only on success
                    if (chatQueue.length > 0 && isAgentRunning && isChatPermissionGranted) {
                        const delay = getRandomInt(CHAT_SEND_DELAY_MIN_MS, CHAT_SEND_DELAY_MAX_MS);
                        console.log(`Scheduling next chat message in ${delay}ms`);
                        setTimeout(() => { isProcessingQueue = false; processChatQueue(); }, delay); // Release lock before timeout
                    } else {
                        isProcessingQueue = false; // Release lock if queue empty or permissions changed
                        if (chatQueue.length > 0) processChatQueue(); // Try immediately if queue still has items after permission check
                    }
                    break;
                case 'disabled':
                    console.warn(`Chat send button was disabled for message (via adapter): "${message}". Re-queuing.`);
                    chatQueue.unshift(message); // Put message back at the front
                    const retryDelayDisabled = getRandomInt(3000, 7000); // Delay before retry for disabled button
                    console.log(`Scheduling chat queue retry in ${retryDelayDisabled}ms (button disabled).`);
                    setTimeout(() => { isProcessingQueue = false; processChatQueue(); }, retryDelayDisabled); // Release lock before timeout
                    break;
                case 'not_found':
                    console.error(`Chat input/button not found for message: "${message}". Cannot send. Discarding message and stopping queue for now.`);
                    // Don't re-queue, likely a page structure issue. Keep queue for potential future fix?
                    // chatQueue = []; // Option: Clear queue entirely on element not found
                    isProcessingQueue = false; // Release lock
                    break;
                case 'not_implemented':
                    console.error(`sendChatMessage is not implemented for ${currentPlatformAdapter.platformName}. Cannot send message: "${message}". Discarding.`);
                    isProcessingQueue = false; // Release lock
                    break;
                case 'error':
                default: // Treat any other non-success status as a retryable error
                    console.error(`Adapter failed to send chat message: "${message}" (Status: ${status || 'unknown adapter error'}). Re-queuing.`);
                    chatQueue.unshift(message); // Put message back
                    const retryDelayError = getRandomInt(5000, 10000); // Longer delay on error
                    console.log(`Scheduling chat queue retry in ${retryDelayError}ms (adapter error).`);
                    setTimeout(() => { isProcessingQueue = false; processChatQueue(); }, retryDelayError); // Release lock before timeout
                    break;
            }
        } catch (error) {
            // Catch errors from the adapter promise itself (e.g., if adapter code throws)
            console.error(`Error during adapter sendChatMessage execution for: "${message}". Error:`, error);
            chatQueue.unshift(message); // Requeue on exception too
            const retryDelayException = getRandomInt(5000, 10000);
            console.log(`Scheduling chat queue retry in ${retryDelayException}ms (adapter exception).`);
            setTimeout(() => { isProcessingQueue = false; processChatQueue(); }, retryDelayException); // Release lock before timeout
        }
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
    console.log("Live Stream Chat AI Agent script loaded (Refactored).");

})(); // IIFE 结束