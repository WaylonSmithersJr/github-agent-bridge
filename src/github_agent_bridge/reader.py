from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass

from .models import Notification
from .parser import decode_header_value, extract_body_text, parse_auth_results
from .policy import Policy
from .queue import JobQueue


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str = "INBOX"


class ImapReader:
    """Fast IMAP reader: fetch -> enqueue durable job -> advance high-water.

    It intentionally never dispatches OpenClaw agents. Slow work belongs to ExecutorPool.
    """

    def __init__(self, config: ImapConfig, queue: JobQueue, policy: Policy):
        self.config = config
        self.queue = queue
        self.policy = policy

    def fetch_once(self) -> int:
        last_uid = int(self.queue.get_state("last_uid", "0") or 0)
        count = 0
        imap = imaplib.IMAP4_SSL(self.config.host, self.config.port)
        try:
            imap.login(self.config.username, self.config.password)
            imap.select(self.config.mailbox)
            status, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
            if status != "OK" or not data or not data[0]:
                return 0
            uids = sorted(int(x) for x in data[0].split() if int(x) > last_uid)
            for uid in uids:
                st, msgd = imap.uid("fetch", str(uid), "(RFC822)")
                if st != "OK" or not msgd or not msgd[0]:
                    break
                msg = email.message_from_bytes(msgd[0][1])
                from_addr = decode_header_value(msg.get("From", ""))
                subject = decode_header_value(msg.get("Subject", ""))
                message_id = decode_header_value(msg.get("Message-ID", ""))
                if "notifications@github.com" in from_addr.lower():
                    n = Notification(uid=uid, message_id=message_id, subject=subject, from_addr=from_addr, body=extract_body_text(msg), auth=parse_auth_results(msg))
                    self.queue.enqueue(n, self.policy)
                    count += 1
                self.queue.set_state("last_uid", str(uid))
                imap.uid("store", str(uid), "+FLAGS", "(\\Seen)")
            return count
        finally:
            try:
                imap.logout()
            except Exception:
                pass
