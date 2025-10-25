import os
import time
import smtplib
import threading
import platform
import subprocess
from email.mime.text import MIMEText
try:
    import winsound
except ImportError:
    winsound = None

try:
    from plyer import notification
except ImportError:
    notification = None


class NotificationSystem:
    def __init__(self, config):
        self.config = config
        self.last_notification = 0
        self.threshold = int(config['notification']['threshold'])
        self.debounce = int(config['notification']['debounce_seconds'])
        self._monitoring = False
        self.is_windows = platform.system() == 'Windows'
        # 追加: 閾値クロス検出用の前回カウント
        self.last_task_count = float('inf')
        
    def start_monitoring(self, job_manager):
        self._monitoring = True
        monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(job_manager,),
            daemon=True
        )
        monitor_thread.start()
        print("[NOTIFY] Monitoring started")
    
    def stop(self):
        self._monitoring = False
    
    def _monitor_loop(self, job_manager):
        while self._monitoring:
            try:
                current = job_manager.get_weighted_task_count()
                # 通知条件: 前回 > 閾値 かつ 今回 <= 閾値（+ デバウンス）
                if (
                    self.last_task_count > self.threshold and 
                    current <= self.threshold and
                    time.time() - self.last_notification > self.debounce
                ):
                    message = f"ORCA Pipeline Alert\nRemaining weighted tasks: {current}"
                    self._send_notifications(message)
                    self.last_notification = time.time()
                # 前回値を更新
                self.last_task_count = current
                time.sleep(5)
            except Exception as e:
                print(f"[NOTIFY ERROR] {e}")
                time.sleep(5)
    
    def _send_notifications(self, message):
        print(f"[NOTIFY] {message}")
        
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except:
                pass
        
        popup_done = False
        if notification:
            try:
                notification.notify(
                    title="ORCA Pipeline",
                    message=message,
                    timeout=10
                )
                popup_done = True
            except:
                popup_done = False
        
        if self.is_windows and not popup_done:
            try:
                self._windows_toast("ORCA Pipeline", message)
                popup_done = True
            except Exception as e:
                print(f"[TOAST ERROR] {e}")
        
        self._send_gmail("ORCA Pipeline Alert", message)
    
    def _send_gmail(self, subject, body):
        try:
            gmail_user = os.getenv('GMAIL_USER') or self.config['gmail']['user']
            gmail_password = (os.getenv('GMAIL_APP_PASSWORD') or self.config['gmail']['app_password']).replace(' ', '')
            recipient = os.getenv('GMAIL_RECIPIENT') or self.config['gmail']['recipient']
            
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = gmail_user
            msg['To'] = recipient
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
            server.quit()
            
            print("[GMAIL] Notification sent successfully")
            
        except Exception as e:
            print(f"[GMAIL ERROR] {e}")
    
    def _windows_toast(self, title: str, message: str, duration: int = 5):
        if platform.system() != 'Windows':
            return
        ps_script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
        $textNodes = $xml.GetElementsByTagName('text')
        $textNodes.Item(0).AppendChild($xml.CreateTextNode('{title}')) | Out-Null
        $textNodes.Item(1).AppendChild($xml.CreateTextNode('{message}')) | Out-Null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ORCA Pipeline')
        $notifier.Show($toast)
        Start-Sleep -Seconds {duration}
        """
        subprocess.run([
            'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_script
        ], check=False)
    
    @staticmethod
    def send_error(error_message):
        print(f"[ERROR ALERT] {error_message}")
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONHAND)
            except:
                pass
        if notification:
            try:
                notification.notify(
                    title="ORCA Pipeline ERROR",
                    message=error_message,
                    timeout=15
                )
            except:
                pass
