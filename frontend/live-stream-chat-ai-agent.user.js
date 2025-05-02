// ==UserScript==
// @name         Live Stream Chat AI Agent
// @name:zh-CN   直播聊天室AI智能代理
// @version      1.3.2
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
            chatContainerSelector: '#chat-items', // 聊天容器的选择器
            chatMessageSelector: '.chat-item.danmaku-item', // 新聊天消息元素的选择器

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
            * 获取 Bilibili 聊天容器的 DOM 节点
            * @returns {Node|null} 聊天容器节点或 null
            */
            getChatContainerNode: function () {
                return document.querySelector(this.chatContainerSelector);
            },

            /**
             * 从新添加的 Bilibili 聊天 DOM 节点提取数据
             * @param {Node} node - 新添加到聊天容器的 DOM 节点
             * @returns {{uname: string, content: string}|null}
             */
            extractRealtimeChatData: function (node) {
                // 确保传入的是正确的元素节点
                if (!node || node.nodeType !== Node.ELEMENT_NODE || !node.matches(this.chatMessageSelector)) {
                    // console.warn('[Bilibili Adapter] extractRealtimeChatData: Invalid node received', node);
                    return null;
                }

                // 尝试从 data-* 属性获取数据
                const uname = node.dataset.uname;
                const uid = node.dataset.uid;

                // 尝试从特定子元素获取内容，如果失败则回退到 data-danmaku
                const contentElement = node.querySelector('.danmaku-item-right');
                let content = contentElement ? contentElement.textContent?.trim() : null;
                // 如果特定元素找不到内容，尝试从 data-danmaku 获取
                if (content === null || content === '') {
                    content = node.dataset.danmaku?.trim();
                }

                // 确保提取到了必要的信息
                if (uname && (content || content === '')) { // 允许空内容
                    // console.log(`[Bilibili Adapter] Extracted: uname=${uname}, uid=${uid}, content=${content}`);
                    return {
                        uname: uname,
                        uid: uid || null, // 如果 uid 没取到，则为 null
                        content: content || '' // 确保 content 不是 null
                    };
                } else {
                    console.warn('[Bilibili Adapter] Failed to extract necessary data:', { uname, uid, content }, node);
                    return null;
                }
            },

            // Bilibili 获取历史消息
            extractInitialChatMessages: function () {
                console.log("[Bilibili Adapter] extractInitialChatMessages not implemented yet.");
                // 这里可以尝试选中 #chat-items 下的所有 .chat-item.danmaku-item
                // 并为每个元素调用 extractRealtimeChatData，然后添加到 initialChatBuffer
                // 但要注意处理顺序和去重
                const initialMessages = [];
                const messageNodes = document.querySelectorAll(`${this.chatContainerSelector} ${this.chatMessageSelector}`);
                messageNodes.forEach(node => {
                    const chatData = this.extractRealtimeChatData(node);
                    if (chatData) {
                        const timestamp = parseInt(node.dataset.ts || (Date.now() / 1000).toString(), 10) * 1000 || Date.now(); // 使用 data-ts 或当前时间
                        initialMessages.push({
                            ...chatData,
                            platform: this.platformName,
                            timestamp: timestamp // 尝试使用 B 站的时间戳
                        });
                    }
                });
                // 可能需要排序 TBD
                // 添加到初始缓冲区 (如果实现了 initialChatBuffer)
                // initialChatBuffer.push(...initialMessages);
                console.log(`[Bilibili Adapter] Found ${initialMessages.length} potential initial messages.`);
                return initialMessages; // 返回提取到的消息数组
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
            chatContainerSelector: '#items.yt-live-chat-item-list-renderer', // YouTube iframe 内的聊天列表容器
            chatMessageSelector: 'yt-live-chat-text-message-renderer, yt-live-chat-paid-message-renderer, yt-live-chat-paid-sticker-renderer, yt-live-chat-membership-item-renderer', // YouTube 的各种聊天消息类型

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
             * 从新添加的 YouTube 聊天 DOM 节点提取数据
             * @param {Node} node - 新添加到聊天容器的 DOM 节点
             * @returns {{uname: string, content: string}|null}
             */
            extractRealtimeChatData: (node) => {
                if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;
                // YouTube消息本身就是指定选择器的元素，无需额外检查 node.matches

                try {
                    const authorName = node.querySelector('#author-name')?.textContent.trim() || '未知';
                    let message = '';

                    // 根据不同的消息类型提取内容 (复用旧的 collectChatMessages 逻辑片段)
                    if (node.matches('yt-live-chat-text-message-renderer')) {
                        const messageSpan = node.querySelector('#message');
                        if (messageSpan) {
                            message = Array.from(messageSpan.childNodes).map(child => {
                                if (child.nodeType === Node.TEXT_NODE) { return child.textContent.trim(); }
                                if (child.nodeType === Node.ELEMENT_NODE && child.tagName === 'IMG') {
                                    const alt = child.getAttribute('alt')?.trim() ?? '表情'; return `[${alt}]`;
                                } return '';
                            }).join(' ').replace(/\s+/g, ' ').trim();
                        }
                    } else if (node.matches('yt-live-chat-paid-message-renderer')) {
                        const price = node.querySelector('#purchase-amount')?.textContent.trim() || '';
                        const paidMsg = node.querySelector('#message')?.innerText.trim() || '(无留言)';
                        message = `[SuperChat ${price}] ${paidMsg}`;
                    } else if (node.matches('yt-live-chat-paid-sticker-renderer')) {
                        const price = node.querySelector('#purchase-amount')?.textContent.trim() || '';
                        message = `[SuperSticker ${price}] [发送了超级贴图]`;
                    } else if (node.matches('yt-live-chat-membership-item-renderer')) {
                        const giftText = node.innerText.trim();
                        message = `[会员消息] ${giftText}`;
                    } else {
                        return null; // 未知类型的节点
                    }

                    if (authorName && message) {
                        return { uname: authorName, content: message };
                    }
                } catch (e) {
                    console.error("[YT Adapter] 提取实时聊天数据时出错:", e, node);
                }
                return null;
            },

            /**
            *  获取 YouTube 聊天容器的 DOM 节点 (处理 iframe)
            *  @returns {Node|null} 聊天容器节点或 null
            */
            getChatContainerNode: function () {
                try {
                    const iframe = document.querySelector('iframe#chatframe');
                    if (!iframe) {
                        // console.warn("YouTube Adapter: Chat iframe (#chatframe) not found for observer setup.");
                        return null;
                    }
                    // 确保能访问 contentDocument，否则等待下一轮重试
                    const chatDoc = iframe.contentDocument; // || iframe.contentWindow?.document; // 通常 contentDocument 就够了，且跨域策略更友好
                    if (!chatDoc) {
                        // console.warn("YouTube Adapter: Cannot access chat iframe document yet for observer setup.");
                        return null;
                    }
                    // 在 iframe 内部查找
                    const container = chatDoc.querySelector(this.chatContainerSelector);
                    // if (!container) {
                    //    console.warn(`YT Adapter: Chat container '${this.chatContainerSelector}' not found inside iframe.`);
                    // }
                    return container;
                } catch (err) {
                    // 捕获可能的跨域错误等
                    if (err.name === 'SecurityError') {
                        console.warn("YouTube Adapter: SecurityError accessing chat iframe content. Waiting for permissions or load.");
                    } else {
                        console.error("YouTube Adapter: Error finding chat container node:", err);
                    }
                    return null;
                }
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
            chatContainerSelector: '.chat-scrollable-area__message-container', // Twitch 的聊天消息容器
            chatMessageSelector: '.chat-line__message', // Twitch 的单条聊天消息

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
             * 获取 Twitch 聊天容器的 DOM 节点
             * @returns {Node|null} 聊天容器节点或 null
             */
            getChatContainerNode: function () {
                return document.querySelector(this.chatContainerSelector);
            },

            /**
             * 从新添加的 Twitch 聊天 DOM 节点提取数据
             * @param {Node} node - 新添加到聊天容器的 DOM 节点
             * @returns {{uname: string, content: string}|null}
             */
            extractRealtimeChatData: (node) => {
                if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;
                // 检查节点是否匹配我们的消息选择器
                if (!node.matches(platformAdapters.twitch.chatMessageSelector)) {
                    return null;
                }

                try {
                    // 注意：Twitch 可能有嵌套结构，选择器需精确
                    const usernameSpan = node.querySelector('.chat-author__display-name');
                    // 提取消息内容，考虑文本和表情图片
                    const messageBody = node.querySelector('span[data-a-target="chat-message-text"]');
                    let content = '';
                    if (messageBody) {
                        content = Array.from(messageBody.childNodes).map(child => {
                            if (child.nodeType === Node.TEXT_NODE) {
                                return child.textContent; // 保留原始空格，后面统一 trim
                            } else if (child.nodeType === Node.ELEMENT_NODE && child.tagName === 'IMG') {
                                // 对于表情图片，提取 alt 文本或 src (如果需要区分)
                                return child.getAttribute('alt') || '[表情]';
                            }
                            return ''; // 忽略其他类型的节点，如 <span> 包裹的徽章等
                        }).join('').trim(); // 合并并去除首尾空格
                    }

                    const uname = usernameSpan ? usernameSpan.textContent.trim() : null;

                    if (uname && content) {
                        return { uname, content };
                    }
                } catch (e) {
                    console.error("[Twitch Adapter] 提取实时聊天数据时出错:", e, node);
                }
                return null;
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
    let realtimeChatBuffer = []; // 实时聊天消息缓冲区 { uname, content, platform, timestamp (精确ms) }
    let chatObserver = null; // 聊天区域的 MutationObserver 实例

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

    let currentVideoElement = null; // 跟踪当前使用的视频元素
    let videoReplacementObserver = null; // 用于监视视频替换的Observer

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
        text-align: center;
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
        contentDiv.appendChild(createSwitchControl('main-switch', 'Control'));

        // 聊天权限开关
        contentDiv.appendChild(createSwitchControl('chat-permission', 'Chat Permission'));

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

            // 检查按钮状态：需要主开关打开，并且(我们已经跟踪了一个有效的视频元素 或 适配器能找到一个)
            const videoElement = currentVideoElement || currentPlatformAdapter?.findVideoElement();
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
     * @function startChatObserver
     * @description 初始化并启动 MutationObserver 来实时监视新的聊天消息。
     * 这是在那些动态将新消息添加到 DOM 的平台上捕获聊天的主要方法。
     * 它能处理消息节点被直接添加或被包裹在其他元素内的情况。
     */
    function startChatObserver() {
        // 如果观察器实例已存在，则表示已经在运行，直接返回
        if (chatObserver) {
            console.log("AI Agent: 聊天 MutationObserver 已在运行。");
            return;
        }
        // 检查当前平台适配器是否正确加载并配置了必要的选择器
        if (!currentPlatformAdapter || !currentPlatformAdapter.getChatContainerNode || !currentPlatformAdapter.chatMessageSelector) {
            console.error("AI Agent: 当前平台适配器未正确配置 (缺少 getChatContainerNode 或 chatMessageSelector)，无法启动聊天观察器。");
            return;
        }

        // 使用适配器的方法来获取目标节点
        const targetNode = currentPlatformAdapter.getChatContainerNode();

        if (!targetNode) {
            // 日志可以保持不变，适配器内部可能已经输出了更具体的警告
            console.warn(`AI Agent: 未找到聊天容器 (via adapter for ${currentPlatformAdapter.platformName}). 将在 1 秒后重试...`);
            setTimeout(startChatObserver, 1000);
            return;
        }

        // 如果没有找到目标容器节点 (可能页面还未完全加载)
        if (!targetNode) {
            console.warn(`AI Agent: 未找到聊天容器 (${currentPlatformAdapter.chatContainerSelector})。将在 1 秒后重试...`);
            // 设置一个短暂的延时后重试启动过程
            setTimeout(startChatObserver, 1000);
            return;
        }

        // 找到容器，准备启动观察器
        console.log(`AI Agent: 找到聊天容器，准备启动 Observer:`, targetNode);

        // 定义当观察到 DOM 变动时执行的回调函数
        const observerCallback = (mutationsList) => {
            // 遍历所有发生的变动记录
            for (const mutation of mutationsList) {
                // 我们只关心子节点列表的变化 (childList)，并且确实有节点被添加 (addedNodes)
                if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                    // 遍历所有被添加的节点
                    mutation.addedNodes.forEach(node => {
                        // 确保我们处理的是 HTML 元素节点 (类型为 1)，忽略文本节点等
                        if (node.nodeType !== Node.ELEMENT_NODE) return;

                        let messageNode = null; // 用于存储最终找到的消息节点

                        // 检查 1：被添加的节点本身是否就是我们要找的聊天消息元素？
                        // 使用平台适配器中定义的 chatMessageSelector 进行匹配
                        if (node.matches(currentPlatformAdapter.chatMessageSelector)) {
                            messageNode = node; // 如果是，直接使用这个节点
                            // console.log('[调试 Observer] 添加的节点本身就是消息节点:', messageNode);
                        }
                        // 检查 2：如果不是，那么这个被添加的节点内部是否包含了我们要找的聊天消息元素？
                        // (这处理了消息被一个额外的 div 包裹后再添加到容器的情况)
                        // 首先确保该节点支持 querySelector 方法 (某些节点如 <title> 可能不支持)
                        else if (typeof node.querySelector === 'function') {
                            // 在被添加节点的内部查找匹配 chatMessageSelector 的元素
                            const potentialMessageNode = node.querySelector(currentPlatformAdapter.chatMessageSelector);
                            if (potentialMessageNode) {
                                messageNode = potentialMessageNode; // 如果找到了，使用这个内部节点
                                // console.log('[调试 Observer] 在添加的节点内部找到了消息节点:', messageNode);
                            }
                        }

                        // 如果通过以上两种方式之一，成功找到了消息节点 (messageNode 不为 null)
                        if (messageNode) {
                            try {
                                // 调用当前平台适配器的 extractRealtimeChatData 方法来提取用户名和内容
                                const chatData = currentPlatformAdapter.extractRealtimeChatData(messageNode);

                                // 确保提取到了有效的数据 (用户名存在，内容存在或为空字符串)
                                if (chatData && chatData.uname && (chatData.content || chatData.content === '')) {
                                    const timestamp = Date.now(); // 获取当前时间戳
                                    // 构建新的聊天消息对象
                                    const newChat = {
                                        ...chatData, // 包含提取的 uname, content, 可能还有 uid
                                        platform: currentPlatformAdapter.platformName, // 记录平台名称
                                        timestamp: timestamp, // 记录时间戳
                                        // 如果适配器没有提供 uid，尝试用用户名生成哈希作为备用标识符
                                        uid: chatData.uid || generateHash(chatData.uname) || null // 确保有某种唯一标识，即使是临时的
                                    };

                                    // --- 防止重复消息逻辑 开始 ---
                                    const timeWindow = 5000; // 定义一个时间窗口（毫秒），用于检查近期重复消息，例如 5 秒
                                    const bufferToCheck = realtimeChatBuffer.slice(-20); // 只检查实时缓冲区中最近的 20 条消息，以优化性能
                                    // 检查是否存在满足以下条件的已有消息：时间戳接近、用户名相同、内容相同、平台相同
                                    const isDuplicate = bufferToCheck.some(existingChat =>
                                        existingChat.timestamp >= timestamp - timeWindow && // 时间接近
                                        existingChat.uname === newChat.uname &&             // 用户名相同
                                        existingChat.content === newChat.content &&       // 内容相同
                                        existingChat.platform === newChat.platform          // 平台相同
                                        // 如果有可靠的 uid，可以用 existingChat.uid === newChat.uid 进行更精确的判断
                                    );

                                    // 如果不是重复消息
                                    if (!isDuplicate) {
                                        // 将新的聊天消息添加到实时缓冲区
                                        realtimeChatBuffer.push(newChat);
                                        console.log(`[聊天捕获] ${new Date(timestamp).toLocaleTimeString()} | ${newChat.uname}: ${newChat.content.substring(0, 50)}...`);
                                    } else {
                                        // 如果是重复消息，可以选择性地记录日志
                                        console.log(`[聊天捕获] 检测到重复消息并跳过:`, newChat.uname, newChat.content.substring(0, 30));
                                    }
                                    // --- 防止重复消息逻辑 结束 ---

                                } else {
                                    // 如果提取函数返回 null 或无效数据，记录警告
                                    // console.warn('[调试 Observer] 提取到的聊天数据为 null 或无效:', messageNode, chatData);
                                }
                            } catch (extractError) {
                                // 如果在调用 extractRealtimeChatData 时发生错误，捕获并记录
                                console.error('[Observer] 调用 extractRealtimeChatData 时出错:', extractError, messageNode);
                            }
                        }
                        // else {
                        //    // 如果需要调试所有被添加但未被识别为消息或不包含消息的节点，可以取消下面的注释
                        //    // console.log('[调试 Observer] 添加的节点不是消息节点，也不包含消息节点:', node);
                        // }
                    });

                    // 限制实时聊天缓冲区的最大长度，防止内存无限增长
                    const MAX_BUFFER_SIZE = 500; // 示例值：最多保留 500 条
                    if (realtimeChatBuffer.length > MAX_BUFFER_SIZE) {
                        // 如果超出限制，从缓冲区开头删除多余的旧消息
                        realtimeChatBuffer.splice(0, realtimeChatBuffer.length - MAX_BUFFER_SIZE);
                        // console.log(`[Observer] 实时聊天缓冲区已清理，保留最新的 ${MAX_BUFFER_SIZE} 条消息。`);
                    }
                }
            }
        };

        // 创建 MutationObserver 的实例，并将上面定义的回调函数传递给它
        chatObserver = new MutationObserver(observerCallback);

        // 配置观察器的选项
        const config = {
            childList: true, // 观察目标节点的子节点（包括文本节点）的添加和删除
            subtree: false   // 不观察目标节点所有后代节点的变动。
            // 设置为 false 通常性能更好，且足以捕获直接添加到聊天容器的元素（或其包装器）。
            // 如果遇到消息嵌套层级非常深且此设置无效的情况，可以尝试改为 true，但需注意可能的性能影响。
        };

        try {
            // 使用指定的配置，在找到的聊天容器节点 (targetNode) 上启动观察器
            chatObserver.observe(targetNode, config);
            // 打印成功启动的日志，包含观察模式（直接子节点或整个子树）
            console.log(`%cAI Agent: 聊天 MutationObserver 已在节点上成功启动 (模式: ${config.subtree ? '子树监听' : '直接子节点监听'})。`, "color: green; font-weight: bold;", targetNode);

            // 可选：如果适配器实现了 extractInitialChatMessages 方法，可以在启动时尝试获取页面上已有的最后几条消息
            // 这有助于 AI 在刚启动时就能获得一些上下文
            // if (typeof currentPlatformAdapter.extractInitialChatMessages === 'function') {
            //     currentPlatformAdapter.extractInitialChatMessages();
            // }

        } catch (e) {
            // 如果启动观察器时发生错误 (例如，目标节点无效或配置错误)
            console.error("AI Agent: 启动聊天 MutationObserver 失败:", e);
            chatObserver = null; // 将观察器实例重置为 null，表示启动失败
        }
    }

    /**
    * 停止聊天 MutationObserver。
    */
    function stopChatObserver() {
        if (chatObserver) {
            chatObserver.disconnect();
            chatObserver = null;
            console.log("AI Agent: 聊天 MutationObserver 已停止。");
            // 清空缓冲区确保下次启动是干净的
            realtimeChatBuffer = [];
            console.log("AI Agent: 实时聊天缓冲区已清空。");
        }
    }

    /**
         * 启动 AI 代理的核心逻辑。包含初始视频检查和启动监控。
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
        // 启动前再次检查 Room ID
        if (!roomId) {
            console.error(`AI Agent (${currentPlatformAdapter.platformName}): Cannot start, invalid Room/Video ID: ${roomId}. Trying refetch...`);
            // 尝试重新获取一次roomId，如果失败则提示并退出
            waitForRoomId(currentPlatformAdapter, 1, 100).then(refetchedId => {
                if (refetchedId) {
                    roomId = refetchedId;
                    console.log(`Room ID re-fetched: ${roomId}. Please click Start again.`);
                    alert("已重新获取房间ID，请再次点击 Start。");
                } else {
                    alert("错误：无法获取房间/视频 ID。请检查页面或刷新重试。");
                }
            });
            return; // 退出当前启动尝试
        }

        console.log("Attempting to start AI Agent...");

        // 启动前先检查视频元素是否存在
        const initialVideoElement = currentPlatformAdapter.findVideoElement();
        if (!initialVideoElement) {
            console.error(`AI Agent (${currentPlatformAdapter.platformName}): Cannot start, initial video element not found.`);
            alert("错误：启动时未找到视频元素。请确保直播已加载。");
            runButton.disabled = true; // 保持禁用，需要用户干预或等待
            return;
        }

        // 尝试使用找到的元素初始化音频
        // 注意：initializeAudio 现在接收 videoElement 参数
        if (initializeAudio(initialVideoElement)) { // <--- 传入找到的元素
            isAgentRunning = true; // 设置代理运行状态标志
            startRecordingCycle(); // 开始录制循环 (使用已初始化的 destination)
            startChatObserver();   // 启动聊天监听器
            startVideoReplacementObserver(); // <--- 启动视频替换监视

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
            // 即使音频失败，如果主开关打开，按钮也应可用，以便用户重试
            runButton.disabled = !isMainSwitchOn;
            currentVideoElement = null; // 初始化失败时，清除跟踪的元素
        }
    }

    /**
     * 停止 AI 代理的核心逻辑。包含停止视频监控和清理资源。
     */
    function stopAgent() {
        if (!isAgentRunning) {
            // console.warn("Agent is not running."); // 可以取消注释方便调试
            return;
        }
        console.log("Stopping AI Agent...");
        isAgentRunning = false; // 清除代理运行状态标志 *先于* 停止其他组件

        stopVideoReplacementObserver(); // <--- 停止视频监视
        stopRecordingAndProcessing(); // 停止录制和处理流程
        stopChatObserver(); // 停止chat监听器
        cleanupAudioResources(); // <--- 调用清理音频资源的函数

        // 更新按钮状态
        runButton.textContent = 'Start'; // 中文
        runButton.classList.remove('running');
        // 确保主开关打开且(当前跟踪的视频元素存在 或 适配器能找到视频元素)时，按钮是可用的
        // <--- 修改了按钮状态检查逻辑
        runButton.disabled = !(isMainSwitchOn && !!(currentVideoElement || currentPlatformAdapter?.findVideoElement()));

        currentVideoElement = null; // <--- 清除跟踪的视频元素引用

        console.log("AI Agent stopped.");
    }

    /**
     * 停止 AI 代理的核心逻辑。包含停止视频监控和清理资源。
     */
    function stopAgent() {
        if (!isAgentRunning) {
            // console.warn("Agent is not running."); // 可以取消注释方便调试
            return;
        }
        console.log("Stopping AI Agent...");
        isAgentRunning = false; // 清除代理运行状态标志 *先于* 停止其他组件

        stopVideoReplacementObserver(); // <--- 停止视频监视
        stopRecordingAndProcessing(); // 停止录制和处理流程
        stopChatObserver(); // 停止chat监听器
        cleanupAudioResources(); // <--- 调用清理音频资源的函数

        // 更新按钮状态
        runButton.textContent = 'Start'; // 中文
        runButton.classList.remove('running');
        // 确保主开关打开且(当前跟踪的视频元素存在 或 适配器能找到视频元素)时，按钮是可用的
        // <--- 修改了按钮状态检查逻辑
        runButton.disabled = !(isMainSwitchOn && !!(currentVideoElement || currentPlatformAdapter?.findVideoElement()));

        currentVideoElement = null; // <--- 清除跟踪的视频元素引用

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
      * 初始化或重新初始化 AudioContext 并连接视频元素源。
      * 现在接受要使用的视频元素。
      * @param {HTMLVideoElement} videoElement - 要连接的视频元素。
      * @returns {boolean} True 如果成功, false 否则。
      */
    function initializeAudio(videoElement) {
        // 检查传入的 videoElement 是否有效且已连接到 DOM
        if (!videoElement || !videoElement.isConnected) {
            console.error("无法初始化音频: 提供的 video 元素无效或已断开连接。");
            currentVideoElement = null; // 确保清除跟踪的元素
            return false;
        }
        console.log("使用 video 元素初始化音频:", videoElement);

        // 检查视频状态和音轨 (可选，有助于调试)
        if (videoElement.readyState < 1) { console.warn(`视频 readyState (${videoElement.readyState}) 过低。`); }
        const audioTracks = getVideoAudioTracks(videoElement); // 使用辅助函数
        if (audioTracks.length === 0 && videoElement.readyState < 3) { console.warn("视频可能还没有音轨。"); }

        try {
            // 如果需要，初始化 AudioContext (只在第一次或关闭后)
            if (!audioContext || audioContext.state === 'closed') {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                console.log("AudioContext 已创建/重新创建。状态:", audioContext.state);
            }
            // 尝试恢复挂起的 AudioContext
            if (audioContext.state === 'suspended') {
                audioContext.resume().then(() => console.log("AudioContext 已恢复。"))
                    .catch(e => console.error("恢复 AudioContext 失败:", e));
            }

            // --- 关键：只在节点不存在时创建它们 ---
            if (!destination) {
                // destination 是录音器使用的目标，不能重新创建，否则录音会断开！
                destination = audioContext.createMediaStreamDestination();
                console.log("MediaStreamAudioDestinationNode 已创建。");
            }
            if (!gainNode) {
                gainNode = audioContext.createGain(); // 音量控制节点
                console.log("GainNode 已创建。");
            }

            // --- 重新连接 *源* 节点 ---
            // 1. 断开 *旧的* 源节点 (如果存在)
            if (mediaElementSource) {
                try {
                    mediaElementSource.disconnect();
                    console.log("已断开旧的 MediaElementSource。");
                } catch (e) { console.warn("断开旧源时出现小错误:", e); }
                mediaElementSource = null; // 清除引用
            }

            // 2. 创建并连接 *新的* 源节点
            try {
                // 直接从新的 videoElement 创建
                mediaElementSource = audioContext.createMediaElementSource(videoElement);
                console.log("为 video 创建了新的 MediaElementSource:", videoElement);
            } catch (sourceError) { // 处理创建错误 (例如元素没有音轨)
                console.error("创建 MediaElementSource 时出错:", sourceError);
                // 尝试使用 captureStream 作为备选方案
                if (videoElement.captureStream && getVideoAudioTracks(videoElement).length > 0) {
                    console.log("尝试使用 captureStream() 作为备选方案。");
                    try {
                        const mediaStream = videoElement.captureStream();
                        mediaElementSource = audioContext.createMediaStreamSource(mediaStream);
                        console.log("已从 captureStream 创建备选 MediaStreamSource。");
                    } catch (fallbackErr) {
                        console.error("captureStream() 备选方案也失败了:", fallbackErr);
                        throw sourceError; // 如果备选失败，重新抛出原始错误
                    }
                } else {
                    throw sourceError; // 如果没有备选方案，重新抛出错误
                }
            }

            // 3. 连接音频管线:
            // 新源 -> 音量控制 -> 录音目标 (destination)
            // 音量控制 -> 扬声器 (audioContext.destination)
            mediaElementSource.connect(gainNode);
            gainNode.connect(destination); // 连接到录音器使用的目标！
            gainNode.connect(audioContext.destination); // 连接到实际扬声器

            console.log("音频节点已重新连接。");
            updateGain(); // 应用当前的音量/静音设置

            // *** 重要：更新跟踪的视频元素引用 ***
            currentVideoElement = videoElement;
            console.log("跟踪的视频元素已更新。");

            return true; // 初始化/重新初始化成功

        } catch (error) {
            console.error("音频初始化/重新初始化期间出错:", error);
            // 清理可能部分创建的 *源* 节点
            if (mediaElementSource) { try { mediaElementSource.disconnect(); } catch (e) { } mediaElementSource = null; }
            // 不要销毁 gainNode 和 destination，它们可能可以重用
            currentVideoElement = null; // 失败时清除跟踪的元素
            return false; // 操作失败
        }
    }

    /** 辅助函数：可靠地获取视频音轨 */
    function getVideoAudioTracks(videoEl) {
        if (!videoEl) return [];
        try {
            // 优先使用 captureStream，兼容 mozCaptureStream
            const stream = videoEl.captureStream ? videoEl.captureStream() : (videoEl.mozCaptureStream ? videoEl.mozCaptureStream() : null);
            return stream ? stream.getAudioTracks() : [];
        } catch (e) {
            // 忽略错误，例如在元素还没准备好时调用
            // console.warn("获取音轨时出错 (captureStream 可能未就绪/不允许):", e.message);
            return [];
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
                    // const chats = currentPlatformAdapter.collectChatMessages(recordingStartTimestamp, recordingEndTimestamp);
                    const screenshotBlob = await captureScreenshot(); // 捕获屏幕截图 (uses adapter's findVideoElement)
                    sendDataToServer(audioBlob, recordingStartTimestamp, recordingEndTimestamp, screenshotBlob); // 发送数据
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

            // 如果代理仍在运行，尝试检查视频元素并重新初始化音频系统作为恢复手段
            if (isAgentRunning) {
                console.warn(`录制器错误发生，尝试检查视频元素并恢复...`);
                checkForVideoReplacement(); // 调用检查函数，它会处理后续逻辑
            }
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
    * 将音频、过滤后的实时弹幕和截图发送到后端 API。
    * 处理累积逻辑。发送后清理过时的实时弹幕缓冲区。
    * @param { Blob | null } audioBlob - 录制的音频数据(可以是 null).
    * @param { number } currentRecordingStartTimestamp - * 刚结束 * 的录制块的开始时间戳(ms)
    * @param { number } currentRecordingEndTimestamp - * 刚结束 * 的录制块的结束时间戳(ms)
    * @param { Blob | null } screenshotBlob - 捕获的屏幕截图 blob，或 null。
    */
    function sendDataToServer(audioBlob, currentRecordingStartTimestamp, currentRecordingEndTimestamp, screenshotBlob) {

        // --- 1. 从实时缓冲区过滤当前时间段的聊天记录 ---
        const chatsForThisInterval = realtimeChatBuffer.filter(chat =>
            chat.timestamp >= currentRecordingStartTimestamp && chat.timestamp < currentRecordingEndTimestamp
        );
        console.log(`[Send Data] 从实时缓冲区过滤到 ${chatsForThisInterval.length} 条聊天消息 (时间范围: ${currentRecordingStartTimestamp} - ${currentRecordingEndTimestamp})`);

        // --- 2. 清理实时缓冲区 (移除比当前结束时间更早的消息) ---
        // 注意: 使用 `>=` 是为了保留恰好在结束瞬间或之后到达的消息给下一个周期
        const originalBufferSize = realtimeChatBuffer.length;
        realtimeChatBuffer = realtimeChatBuffer.filter(chat => chat.timestamp >= currentRecordingEndTimestamp);
        if (realtimeChatBuffer.length < originalBufferSize) {
            console.log(`[Send Data] 实时聊天缓冲区已清理，移除 ${originalBufferSize - realtimeChatBuffer.length} 条旧消息。`);
        }

        // --- 3. 检查是否有有效数据发送 ---
        if ((!audioBlob || audioBlob.size === 0) && chatsForThisInterval.length === 0 && !screenshotBlob) {
            console.log("[Send Data] 没有有效数据（音频、过滤后的聊天、截图）需要发送。");
            return; // 没有可发送的数据，直接返回
        }

        // --- 4. 处理音频累积逻辑 (与之前类似，但针对 audioBlob) ---
        if (isSending) {
            console.log('[Send Data] 上一个请求正在进行中。累积音频块 (如果存在)...');
            if (audioBlob && audioBlob.size > 0) {
                if (!isAccumulating) {
                    accumulatedChunks = [audioBlob]; // 开始新的累积
                    isAccumulating = true;
                } else {
                    accumulatedChunks.push(audioBlob); // 添加到现有累积中
                }
            }
            // 聊天记录已基于时间过滤，截图通常不需要累积
            return;
        }

        // 合并累积的音频块
        let finalAudioBlob = audioBlob;
        if (isAccumulating && accumulatedChunks.length > 0) {
            console.log(`[Send Data] 合并 ${accumulatedChunks.length} 个累积的音频块与当前块 (如果有)。`);
            const chunksToMerge = audioBlob ? [audioBlob, ...accumulatedChunks] : [...accumulatedChunks];
            if (chunksToMerge.length > 0) {
                finalAudioBlob = new Blob(chunksToMerge, { type: chunksToMerge[0].type });
                console.log(`[Send Data] 合并后的音频 Blob 大小: ${finalAudioBlob.size} bytes`);
            } else {
                finalAudioBlob = null;
            }
            accumulatedChunks = [];
            isAccumulating = false;
        }

        // --- 5. 准备并发送数据 ---
        isSending = true; // 设置发送锁
        const dataSize = finalAudioBlob ? finalAudioBlob.size : 0;
        const screenshotSize = screenshotBlob ? screenshotBlob.size : 0;
        console.log(`[Send Data] 准备发送数据。音频: ${dataSize} bytes, 聊天: ${chatsForThisInterval.length}, 截图: ${screenshotSize} bytes.`);

        const formData = new FormData();
        if (finalAudioBlob && finalAudioBlob.size > 0) {
            formData.append('audio', finalAudioBlob, `audio_${Date.now()}.webm`);
        }
        // **使用过滤后的聊天记录**
        formData.append('chats', JSON.stringify(chatsForThisInterval));
        formData.append('roomId', roomId || 'unknown');
        formData.append('platform', currentPlatformAdapter.platformName);

        if (screenshotBlob && screenshotBlob.size > 0) {
            const timestampStr = new Date(currentRecordingEndTimestamp).toISOString().replace(/[:.]/g, "-"); // 使用结束时间
            const screenshotFilename = `${roomId || 'unknown'}_${timestampStr}.jpg`;
            formData.append('screenshot', screenshotBlob, screenshotFilename);
        }
        // **使用传入的时间戳**
        formData.append('startTimestamp', currentRecordingStartTimestamp.toString());
        formData.append('endTimestamp', currentRecordingEndTimestamp.toString());

        // --- 6. 使用 XMLHttpRequest 发送 ---
        const xhr = new XMLHttpRequest();
        xhr.open('POST', API_ENDPOINT, true);
        xhr.timeout = 90000;

        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) {
                console.log(`[XHR] Upload complete. Status: ${xhr.status}`);
                isSending = false; // **释放锁**

                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        const resp = JSON.parse(xhr.responseText);
                        console.log('Server Response:', resp);
                        if (resp.status === 'success') {
                            console.log('Server processed data successfully.');
                            const parsed = parseServerResponse(resp);
                            console.log('> Youdao STT    :', parsed.youdao);
                            console.log('> Whisper STT   :', parsed.whisper);
                            console.log('> Internal Think:', parsed.think);
                            console.log('> Continues     :', parsed.continues);
                            console.log('> Notepad Notes :', parsed.notepadNotes);
                            console.log('> Image URL     :', parsed.imageUrl);
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
                            console.error('Server returned an application error:', resp.message || "No error message provided.", resp);
                        }
                    } catch (e) {
                        console.error('Failed to parse JSON response:', e);
                        console.error('Raw Response Text:', xhr.responseText);
                    }

                } else {
                    console.error(`Failed to send data. HTTP Status: ${xhr.status} ${xhr.statusText}`);
                    console.error('Response Text:', xhr.responseText);
                }

                // --- 处理累积音频 (XHR 完成后) ---
                if (isAccumulating && accumulatedChunks.length > 0) {
                    console.log("[Send Data] 在发送完成后处理累积的音频块。");
                    const nextBlob = accumulatedChunks.shift(); // 取出第一个
                    if (accumulatedChunks.length === 0) isAccumulating = false; // 更新状态

                    if (nextBlob) {
                        // 重要：累积的音频没有对应的聊天和截图，需要明确这一点
                        // 传递的时间戳也应该是它们原始的时间范围，但我们这里没有存储，
                        // 最简单的做法是传 null 或一个特殊标记，或者不传时间戳。
                        // 这里我们简化处理，不传递上次聊天/截图/精确时间戳，只发送音频。
                        // 或者，更好的是，将累积块与下一个常规块一起发送。
                        // 当前实现是在 isSending 为 false 后，如果有累积块则立即发送。
                        // 这意味着它没有最新的聊天/截图。
                        console.warn("[Send Data] 立即发送累积的音频块，无关联的聊天/截图。");
                        // 注意：调用 sendDataToServer 时，时间戳参数可能无意义或需要特殊处理
                        // 为了简单，这里传递 0 或一个标记，后端需要能处理这种情况。
                        // 这里我们还是用上次的时间戳，虽然不精确。
                        sendDataToServer(nextBlob, currentRecordingStartTimestamp, currentRecordingEndTimestamp, null);
                    } else {
                        console.warn("[Send Data] 累积队列状态异常。");
                        isAccumulating = false; // 重置状态
                    }
                } // 结束处理累积音频
            } // 结束 readyState === 4
        }; // 结束 onreadystatechange

        xhr.onerror = function () { // 网络错误
            console.error('[XHR] Network error occurred during upload.');
            isSending = false; // **释放锁**
            // 处理累积音频
            if (isAccumulating && accumulatedChunks.length > 0) {
                console.log("[Send Data] 网络错误后处理累积的块。");
                const nextBlob = accumulatedChunks.shift();
                if (accumulatedChunks.length === 0) isAccumulating = false;
                if (nextBlob) {
                    console.warn("[Send Data] 发送累积音频，无关联聊天/截图。");
                    sendDataToServer(nextBlob, currentRecordingStartTimestamp, currentRecordingEndTimestamp, null);
                } else { isAccumulating = false; }
            }
        };
        xhr.ontimeout = function () { // 请求超时
            console.error('[XHR] Request timed out.');
            isSending = false; // **释放锁**
            // 处理累积音频
            if (isAccumulating && accumulatedChunks.length > 0) {
                console.log("[Send Data] 请求超时后处理累积的块。");
                const nextBlob = accumulatedChunks.shift();
                if (accumulatedChunks.length === 0) isAccumulating = false;
                if (nextBlob) {
                    console.warn("[Send Data] 发送累积音频，无关联聊天/截图。");
                    sendDataToServer(nextBlob, currentRecordingStartTimestamp, currentRecordingEndTimestamp, null);
                } else { isAccumulating = false; }
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
            currentMaxChatLength = 100; // YouTube默认切分值
        } else if (currentPlatformAdapter?.platformName === 'Bilibili') {
            currentMaxChatLength = 20; // Bilibili默认切分值
        } else if (currentPlatformAdapter?.platformName === 'Twitch') {
            currentMaxChatLength = 100; // Twitch默认切分值
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

    // 辅助函数：用于生成基于用户名的哈希值，作为备用 UID
    // 注意：这是一个非常基础的哈希函数，主要用于临时标识，可能存在碰撞
    function generateHash(str) {
        if (!str) return null;
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash |= 0; // Convert to 32bit integer
        }
        return String(hash); // 返回字符串形式
    }

    /**
 * 启动 MutationObserver 来观察视频元素的替换。
 */
    function startVideoReplacementObserver() {
        if (videoReplacementObserver) return; // 已经在运行

        // 定义观察到变化时的回调
        const observerCallback = (mutationsList, observer) => {
            // 可以添加防抖/节流来避免过于频繁的检查，但通常不是必需的
            checkForVideoReplacement();
        };

        videoReplacementObserver = new MutationObserver(observerCallback);

        // 监视 body 下的所有子节点添加/删除，这样比较通用
        // 如果性能有问题，可以尝试监视更精确的父容器
        const targetNode = document.body;
        const config = { childList: true, subtree: true }; // 监视子节点和整个子树

        try {
            videoReplacementObserver.observe(targetNode, config);
            console.log("%cAI Agent: 视频替换监视器已启动。", "color: orange;");
        } catch (e) {
            console.error("启动视频替换监视器失败:", e);
            videoReplacementObserver = null;
        }
    }

    /**
     * 停止视频替换监视器。
     */
    function stopVideoReplacementObserver() {
        if (videoReplacementObserver) {
            videoReplacementObserver.disconnect();
            videoReplacementObserver = null;
            console.log("%cAI Agent: 视频替换监视器已停止。", "color: orange;");
        }
    }

    /**
     * 检查视频元素是否需要重新初始化。
     * 由监视器回调或其他错误处理程序调用。
     */
    function checkForVideoReplacement() {
        if (!isAgentRunning) return; // 仅在代理运行时检查

        // 尝试使用适配器找到当前有效的视频元素
        const newVideoElement = currentPlatformAdapter.findVideoElement();

        // 情况 1: 当前找不到任何视频元素
        if (!newVideoElement) {
            if (currentVideoElement) {
                // 之前有跟踪的元素，但现在找不到了
                console.warn("跟踪的视频元素丢失，且未找到新的。");
                // 可以选择停止代理或等待。这里先清除引用并等待。
                currentVideoElement = null;
            }
            // 如果本来就没有跟踪的元素 (currentVideoElement === null)，则无需操作
            return;
        }

        // 情况 2: 找到了视频元素，需要判断是否要更新
        // 条件 1: 之前没有跟踪元素 (刚启动或丢失后重新找到)
        // 条件 2: 之前跟踪的元素从 DOM 中移除了 (!isConnected)
        // 条件 3: 找到的元素和之前跟踪的不是同一个元素
        const oldElementLost = currentVideoElement && !currentVideoElement.isConnected;
        const foundDifferentElement = newVideoElement !== currentVideoElement;

        if (!currentVideoElement || oldElementLost || foundDifferentElement) {
            // 打印原因，方便调试
            if (oldElementLost) console.log("检测到跟踪的视频元素已断开连接。");
            else if (foundDifferentElement && currentVideoElement) console.log("检测到不同的视频元素。");
            else if (!currentVideoElement) console.log("检测到初始/新的视频元素。");

            // 调用重新初始化流程
            reinitializeAudioSystem(newVideoElement);
        }

        // 情况 3: 找到的元素和跟踪的是同一个，且已连接 - 无需操作
    }

    /**
     * 处理因视频更改而重新初始化音频的过程。
     * @param {HTMLVideoElement} newVideoElement - 要使用的新视频元素。
     */
    function reinitializeAudioSystem(newVideoElement) {
        // 再次检查代理是否仍在运行
        if (!isAgentRunning) {
            console.warn("代理已停止，跳过音频重新初始化。");
            return;
        }
        console.log("%cAI Agent: 正在为新的视频元素重新初始化音频系统...", "color: blue; font-weight: bold;");

        // 尝试重新初始化音频连接 (这个函数会更新 currentVideoElement)
        if (initializeAudio(newVideoElement)) {
            // 如果成功，通常不需要重启 MediaRecorder，因为它们连接的是 destination.stream
            console.log("%cAI Agent: 音频系统成功重新初始化。", "color: blue;");
        } else {
            // 如果重新初始化失败，这可能是一个严重问题
            console.error("重新初始化音频系统失败。代理可能停止捕获音频！");
            // 可以考虑在这里停止代理，防止后续错误
            // stopAgent();
        }
    }

    /**
    * 集中清理音频相关资源。
    */
    function cleanupAudioResources() {
        console.log("正在清理音频资源...");

        // 停止可能仍在运行的录制器 (以防万一)
        if (mediaRecorder1 && mediaRecorder1.state !== 'inactive') try { mediaRecorder1.stop() } catch (e) {/*忽略停止错误*/ }
        if (mediaRecorder2 && mediaRecorder2.state !== 'inactive') try { mediaRecorder2.stop() } catch (e) {/*忽略停止错误*/ }
        mediaRecorder1 = null; recorder1Timeout = null;
        mediaRecorder2 = null; recorder2Timeout = null;
        chunks1 = []; chunks2 = []; accumulatedChunks = []; isAccumulating = false;

        // 断开音频节点连接
        if (gainNode) try { gainNode.disconnect(); } catch (e) { }
        if (mediaElementSource) try { mediaElementSource.disconnect(); } catch (e) { }
        if (destination) try { destination.disconnect(); } catch (e) { } // 通常不需要，但以防万一

        // 可选：完全关闭 AudioContext (如果确定不再需要)
        // if (audioContext && audioContext.state !== 'closed') {
        //    audioContext.close().then(() => console.log("AudioContext closed.")).catch(e => console.error("Error closing AudioContext:", e));
        //    audioContext = null; // 关闭后需要设为 null
        //    destination = null; // Context 关闭后，destination 也无效了
        // } else {
        // 如果不关闭 Context，则不清空 audioContext 和 destination 引用
        // }
        mediaElementSource = null; // 源总是需要清除
        gainNode = null;           // gainNode 也清除

        console.log("音频资源已清理。");
    }

    // --- 脚本入口点 ---
    console.log("Live Stream Chat AI Agent script loaded (Refactored).");

})(); // IIFE 结束