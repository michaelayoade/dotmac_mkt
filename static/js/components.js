/**
 * Alpine.js CSP-compatible component registrations.
 *
 * All Alpine logic lives here as named Alpine.data() components.
 * Templates reference them by name: x-data="componentName"
 * Server data is passed via data-* attributes, parsed in init().
 */
document.addEventListener('alpine:init', function () {

    // ── Dark Mode (global store, accessed via $store.dark) ───────────
    Alpine.store('dark', {
        on: localStorage.getItem('darkMode') === 'true',
        toggle: function () {
            this.on = !this.on;
            localStorage.setItem('darkMode', String(this.on));
        },
        isOff: function () {
            return !this.on;
        }
    });

    // ── Toast Store (used in base.html toast container) ──────────────
    Alpine.data('toastStore', function () {
        return {
            toasts: [],
            addToast: function (detail) {
                var self = this;
                var id = Date.now();
                this.toasts.push({
                    id: id,
                    message: detail.message,
                    type: detail.type || 'info',
                    visible: true
                });
                setTimeout(function () { self.removeToast(id); }, detail.duration || 4000);
            },
            removeToast: function (id) {
                var self = this;
                var toast = this.toasts.find(function (t) { return t.id === id; });
                if (toast) {
                    toast.visible = false;
                    setTimeout(function () {
                        self.toasts = self.toasts.filter(function (t) { return t.id !== id; });
                    }, 300);
                }
            },
            isSuccess: function (toast) { return toast.type === 'success'; },
            isError: function (toast) { return toast.type === 'error'; },
            isWarning: function (toast) { return toast.type === 'warning'; },
            isInfo: function (toast) { return toast.type === 'info'; }
        };
    });

    // ── Notification Bell (used in admin topbar) ─────────────────────
    Alpine.data('notificationBell', function () {
        return {
            open: false,
            unreadCount: 0,
            notifications: [],
            ws: null,
            reconnectTimer: null,

            init: function () {
                this.fetchNotifications();
                this.connectWebSocket();
                var self = this;
                setInterval(function () { self.fetchUnreadCount(); }, 60000);
            },

            toggle: function () {
                this.open = !this.open;
                if (this.open) this.fetchNotifications();
            },

            fetchNotifications: async function () {
                try {
                    var token = this.getToken();
                    if (!token) return;
                    var resp = await fetch('/notifications/me?limit=10', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    if (resp.ok) {
                        var data = await resp.json();
                        this.notifications = data.items || [];
                        this.fetchUnreadCount();
                    }
                } catch (e) { console.debug('[Notifications] fetch failed:', e); }
            },

            fetchUnreadCount: async function () {
                try {
                    var token = this.getToken();
                    if (!token) return;
                    var resp = await fetch('/notifications/me/unread-count', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    if (resp.ok) {
                        var data = await resp.json();
                        this.unreadCount = data.count;
                    }
                } catch (e) {}
            },

            markRead: async function (n) {
                if (n.is_read) return;
                try {
                    var token = this.getToken();
                    if (!token) return;
                    await fetch('/notifications/me/' + n.id + '/read', {
                        method: 'POST',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    n.is_read = true;
                    this.unreadCount = Math.max(0, this.unreadCount - 1);
                } catch (e) {}
            },

            markAllRead: async function () {
                try {
                    var token = this.getToken();
                    if (!token) return;
                    await fetch('/notifications/me/read-all', {
                        method: 'POST',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    this.notifications.forEach(function (n) { n.is_read = true; });
                    this.unreadCount = 0;
                } catch (e) {}
            },

            connectWebSocket: function () {
                var self = this;
                var token = this.getToken();
                if (!token) return;
                var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                var wsUrl = protocol + '//' + window.location.host + '/ws/notifications';
                try {
                    this.ws = new WebSocket(wsUrl, [token]);
                    this.ws.onmessage = function (event) {
                        try {
                            var data = JSON.parse(event.data);
                            if (data.type === 'notification') {
                                self.unreadCount++;
                                self.notifications.unshift(data.notification);
                                if (self.notifications.length > 10) self.notifications.pop();
                                window.showToast(data.notification.title, 'info');
                            }
                        } catch (e) {}
                    };
                    this.ws.onclose = function () { self.scheduleReconnect(); };
                    this.ws.onerror = function () { if (self.ws) self.ws.close(); };
                } catch (e) {
                    this.scheduleReconnect();
                }
            },

            scheduleReconnect: function () {
                var self = this;
                if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
                this.reconnectTimer = setTimeout(function () { self.connectWebSocket(); }, 5000);
            },

            getToken: function () {
                var match = document.cookie.match(/(?:^|;\s*)access_token=([^;]*)/);
                return match ? match[1] : '';
            },

            destroy: function () {
                if (this.ws) { this.ws.close(); this.ws = null; }
                if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
            },

            hasUnread: function () { return this.unreadCount > 0; },
            formatCount: function () { return this.unreadCount > 99 ? '99+' : String(this.unreadCount); },
            isUnread: function (n) { return !n.is_read; },
            actionUrl: function (n) { return n.action_url || '#'; },
            messageText: function (n) { return n.message || ''; }
        };
    });

    // ── User Menu dropdown (used in admin topbar) ────────────────────
    Alpine.data('userMenu', function () {
        return {
            open: false,
            toggle: function () { this.open = !this.open; },
            close: function () { this.open = false; }
        };
    });

    // ── Sidebar Toggle (used in admin/base.html mobile overlay) ──────
    Alpine.data('sidebarToggle', function () {
        return {
            open: false,
            toggle: function () { this.open = !this.open; },
            close: function () { this.open = false; }
        };
    });

    // ── Demo Counter (used on index.html) ────────────────────────────
    Alpine.data('demoCounter', function () {
        return {
            count: 214,
            increment: function () { this.count = this.count + 1; }
        };
    });

    // ── Branding Editor (used in branding.html) ──────────────────────
    // Server data passed via data-initial='{{ ... | tojson }}'
    Alpine.data('brandingEditor', function () {
        return {
            primary: '',
            accent: '',
            displayFont: '',
            bodyFont: '',
            init: function () {
                var raw = this.$el.dataset.initial;
                if (raw) {
                    var d = JSON.parse(raw);
                    this.primary = d.primary || '';
                    this.accent = d.accent || '';
                    this.displayFont = d.displayFont || '';
                    this.bodyFont = d.bodyFont || '';
                }
            },
            gradientStyle: function () {
                return 'background: linear-gradient(120deg, ' + this.primary + ', ' + this.accent + ')';
            },
            displayFontStyle: function () {
                return 'font-family: ' + this.displayFont;
            },
            bodyFontStyle: function () {
                return 'font-family: ' + this.bodyFont;
            }
        };
    });

    // ── File Upload Zone (used in components/_file_upload.html) ───────
    // Server data passed via data-initial='{{ ... | tojson }}'
    Alpine.data('fileUploadZone', function () {
        return {
            preview: '',
            filename: '',
            init: function () {
                var raw = this.$el.dataset.initial;
                if (raw) {
                    var d = JSON.parse(raw);
                    this.preview = d.preview || '';
                }
            },
            hasPreview: function () { return !!this.preview; },
            noPreview: function () { return !this.preview; },
            onFileChange: function (event) {
                var f = event.target.files[0];
                this.filename = f ? f.name : '';
                if (f) {
                    var self = this;
                    var reader = new FileReader();
                    reader.onload = function (e) { self.preview = e.target.result; };
                    reader.readAsDataURL(f);
                }
            },
            onRemove: function (event) {
                if (event.target.checked) {
                    this.preview = '';
                    this.filename = '';
                }
            }
        };
    });

    // ── File Drop Zone (used in admin/file_uploads/upload.html) ──────
    Alpine.data('fileDropZone', function () {
        return {
            dragging: false,
            fileName: '',
            hasFile: function () { return !!this.fileName; },
            noFile: function () { return !this.fileName; },
            onDragOver: function () { this.dragging = true; },
            onDragLeave: function () { this.dragging = false; },
            onDrop: function (event) {
                this.dragging = false;
                var files = event.dataTransfer.files;
                this.fileName = (files[0] && files[0].name) || '';
                this.$refs.fileInput.files = files;
            },
            onFileChange: function (event) {
                this.fileName = (event.target.files[0] && event.target.files[0].name) || '';
            },
            dropClass: function () {
                return this.dragging
                    ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/10'
                    : 'border-slate-300 dark:border-slate-600 hover:border-primary-400';
            }
        };
    });

});
