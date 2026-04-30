"""Email parser for various encodings and formats."""

import email
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from email.message import Message
from typing import Optional, List, Tuple, Dict, Any
import re
import logging

from .models import Email, EmailAddress, EmailFlag

logger = logging.getLogger(__name__)


class EmailParser:
    """Parser for email messages.
    
    Supports:
    - Multiple encodings (GBK, UTF-8, GB2312, etc.)
    - Nested multipart messages
    - Attachments extraction
    """
    
    # Common Chinese encodings
    CHINESE_ENCODINGS = ['gbk', 'gb2312', 'gb18030', 'big5']
    
    @classmethod
    def parse(cls, raw_bytes: bytes) -> Optional[Email]:
        """Parse raw email bytes into Email model.
        
        Args:
            raw_bytes: Raw email content as bytes
        
        Returns:
            Email model or None if parsing fails
        """
        try:
            msg = email.message_from_bytes(raw_bytes)
            return cls._parse_message(msg)
        except Exception as e:
            logger.error(f"Failed to parse email: {e}")
            return None
    
    @classmethod
    def _parse_message(cls, msg: Message) -> Email:
        """Parse email.message.Message into Email model."""
        # Parse headers
        message_id = msg.get('Message-ID', '')
        subject = cls._decode_header(msg.get('Subject', ''))
        
        # From
        from_str = msg.get('From', '')
        from_addr = cls._parse_address(from_str)
        
        # To
        to_str = msg.get('To', '')
        to_addrs = cls._parse_addresses(to_str)
        
        # Cc
        cc_str = msg.get('Cc', '')
        cc_addrs = cls._parse_addresses(cc_str)
        
        # Date
        date_str = msg.get('Date', '')
        date = None
        if date_str:
            try:
                date = parsedate_to_datetime(date_str)
            except:
                pass
        
        # References
        in_reply_to = msg.get('In-Reply-To', '')
        references_str = msg.get('References', '')
        references = re.findall(r'<([^>]+)>', references_str) if references_str else []
        
        # Parse body and attachments
        text_body, html_body, attachments = cls._parse_body(msg)
        
        # Flags (not available in raw message, set by IMAP)
        flags = []
        
        return Email(
            message_id=message_id,
            subject=subject,
            from_addr=from_addr,
            to_addrs=to_addrs,
            cc_addrs=cc_addrs,
            text_body=text_body,
            html_body=html_body,
            date=date,
            flags=flags,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
            raw_bytes=None  # Don't store raw bytes to save memory
        )
    
    @classmethod
    def _decode_header(cls, header: str) -> str:
        """Decode email header with proper encoding."""
        if not header:
            return ''
        
        try:
            decoded_parts = decode_header(header)
            result = []
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    # Try specified encoding first
                    if encoding:
                        try:
                            result.append(part.decode(encoding))
                            continue
                        except:
                            pass
                    
                    # Try common Chinese encodings
                    for enc in cls.CHINESE_ENCODINGS:
                        try:
                            result.append(part.decode(enc))
                            break
                        except:
                            continue
                    else:
                        # Fallback to UTF-8 with error handling
                        result.append(part.decode('utf-8', errors='replace'))
                else:
                    result.append(part)
            
            return ''.join(result)
        except Exception as e:
            logger.warning(f"Failed to decode header: {e}")
            return str(header)
    
    @classmethod
    def _parse_address(cls, addr_str: str) -> EmailAddress:
        """Parse a single email address."""
        if not addr_str:
            return EmailAddress(address='')
        
        name, address = parseaddr(addr_str)
        name = cls._decode_header(name) if name else None
        
        return EmailAddress(address=address, name=name)
    
    @classmethod
    def _parse_addresses(cls, addrs_str: str) -> List[EmailAddress]:
        """Parse multiple email addresses."""
        if not addrs_str:
            return []
        
        # Split by comma, but handle quoted names
        addresses = []
        current = ''
        in_quotes = False
        
        for char in addrs_str:
            if char == '"':
                in_quotes = not in_quotes
                current += char
            elif char == ',' and not in_quotes:
                if current.strip():
                    addresses.append(cls._parse_address(current.strip()))
                current = ''
            else:
                current += char
        
        if current.strip():
            addresses.append(cls._parse_address(current.strip()))
        
        return addresses
    
    @classmethod
    def _parse_body(cls, msg: Message) -> Tuple[Optional[str], Optional[str], List[dict]]:
        """Parse email body and attachments.
        
        Returns:
            Tuple of (text_body, html_body, attachments)
        """
        text_body = None
        html_body = None
        attachments = []
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = part.get('Content-Disposition', '')
                
                # Check if it's an attachment
                if 'attachment' in content_disposition:
                    attachment = cls._parse_attachment(part)
                    if attachment:
                        attachments.append(attachment)
                    continue
                
                # Parse body content
                if content_type == 'text/plain' and not text_body:
                    text_body = cls._decode_payload(part)
                elif content_type == 'text/html' and not html_body:
                    html_body = cls._decode_payload(part)
        else:
            # Single part message
            content_type = msg.get_content_type()
            if content_type == 'text/plain':
                text_body = cls._decode_payload(msg)
            elif content_type == 'text/html':
                html_body = cls._decode_payload(msg)
        
        return text_body, html_body, attachments
    
    @classmethod
    def _decode_payload(cls, part: Message) -> str:
        """Decode message part payload."""
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                return ''
            
            # Try charset from Content-Type
            charset = part.get_content_charset()
            if charset:
                try:
                    return payload.decode(charset)
                except:
                    pass
            
            # Try common Chinese encodings
            for enc in cls.CHINESE_ENCODINGS:
                try:
                    return payload.decode(enc)
                except:
                    continue
            
            # Fallback to UTF-8
            return payload.decode('utf-8', errors='replace')
        except Exception as e:
            logger.warning(f"Failed to decode payload: {e}")
            return ''
    
    @classmethod
    def _parse_attachment(cls, part: Message) -> Optional[dict]:
        """Parse attachment from message part."""
        try:
            filename = part.get_filename()
            if filename:
                filename = cls._decode_header(filename)
            
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            
            return {
                'filename': filename,
                'content_type': content_type,
                'size': len(payload) if payload else 0,
            }
        except Exception as e:
            logger.warning(f"Failed to parse attachment: {e}")
            return None
