import time
import smtplib
import threading
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
                weighted_count = job_manager.get_weighted_task_count()
                
                if (weighted_count <= self.threshold and 
                    time.time() - self.last_notification > self.debounce):
                    
                    message = f"ORCA Pipeline Alert\nRemaining tasks: {weighted_count}"
                    self._send_notifications(message)
                    self.last_notification = time.time()
                    
                time.sleep(5)
            except Exception as e:
                print(f"[NOTIFY ERROR] {e}")
    
    def _send_notifications(self, message):
        print(f"[NOTIFY] {message}")
        
        # Windows sound notification
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except:
                pass
        
        # Desktop popup notification
        if notification:
            try:
                notification.notify(
                    title="ORCA Pipeline",
                    message=message,
                    timeout=10
                )
            except:
                pass
        
        # Gmail notification
        self._send_gmail("ORCA Pipeline Alert", message)
    
    def _send_gmail(self, subject, body):
        """Send Gmail notification with app password"""
        try:
            gmail_user = self.config['gmail']['user']
            gmail_password = self.config['gmail']['app_password']
            recipient = self.config['gmail']['recipient']
            
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
    
    @staticmethod
    def send_error(error_message):
        """Send immediate error notification"""
        print(f"[ERROR ALERT] {error_message}")
        
        # Critical error sound
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONHAND)
            except:
                pass
                
        # Error popup
        if notification:
            try:
                notification.notify(
                    title="ORCA Pipeline ERROR",
                    message=error_message,
                    timeout=15
                )
            except:
                pass