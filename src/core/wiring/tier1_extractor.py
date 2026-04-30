"""Tier 1 link extractor - email header parsing.

Extracts relationships from email headers:
- Message-ID (email identity)
- In-Reply-To (reply chain)
- References (thread references)
- From/To/Cc (communication graph)
"""

import logging
from typing import List, Optional
import hashlib

from sync.models import Email
from .models import Link, LinkRelation, LinkTier

logger = logging.getLogger(__name__)


class Tier1Extractor:
    """Extract Tier 1 links from email headers.
    
    Tier 1 = 0 token, 100% accurate, from email headers.
    """
    
    def extract(self, email: Email) -> List[Link]:
        """Extract all Tier 1 links from an email.
        
        Args:
            email: Email to extract links from
        
        Returns:
            List of extracted links
        """
        links = []
        email_id = self._get_email_id(email)
        
        # 1. Reply-to relationships
        if email.in_reply_to:
            links.append(Link(
                source_id=email_id,
                target_id=email.in_reply_to,
                relation=LinkRelation.REPLY_TO,
                tier=LinkTier.TIER_1,
                metadata={"type": "in_reply_to"}
            ))
            logger.debug(f"Found reply-to: {email_id} -> {email.in_reply_to}")
        
        # 2. References relationships
        for ref_id in email.references:
            links.append(Link(
                source_id=email_id,
                target_id=ref_id,
                relation=LinkRelation.REFERENCES,
                tier=LinkTier.TIER_1,
                weight=0.8,  # References are weaker than direct reply
                metadata={"type": "reference"}
            ))
            logger.debug(f"Found reference: {email_id} -> {ref_id}")
        
        # 3. Sender relationship
        sender_id = self._get_person_id(email.from_addr.address)
        links.append(Link(
            source_id=email_id,
            target_id=sender_id,
            relation=LinkRelation.SENT_BY,
            tier=LinkTier.TIER_1,
            metadata={
                "name": email.from_addr.name,
                "email": email.from_addr.address
            }
        ))
        
        # 4. Recipient relationships
        for to_addr in email.to_addrs:
            recipient_id = self._get_person_id(to_addr.address)
            links.append(Link(
                source_id=email_id,
                target_id=recipient_id,
                relation=LinkRelation.SENT_TO,
                tier=LinkTier.TIER_1,
                metadata={
                    "name": to_addr.name,
                    "email": to_addr.address
                }
            ))
        
        # 5. CC relationships
        for cc_addr in email.cc_addrs:
            cc_id = self._get_person_id(cc_addr.address)
            links.append(Link(
                source_id=email_id,
                target_id=cc_id,
                relation=LinkRelation.CC_TO,
                tier=LinkTier.TIER_1,
                weight=0.7,  # CC is weaker than direct To
                metadata={
                    "name": cc_addr.name,
                    "email": cc_addr.address
                }
            ))
        
        logger.info(f"Extracted {len(links)} Tier 1 links from email {email_id}")
        return links
    
    def _get_email_id(self, email: Email) -> str:
        """Get unique ID for email.
        
        Uses Message-ID if available, otherwise generates hash from content.
        """
        if email.message_id:
            # Normalize Message-ID (remove angle brackets if present)
            msg_id = email.message_id.strip('<>')
            return f"email:{msg_id}"
        
        # Fallback: generate hash from content
        content = f"{email.subject}:{email.from_addr.address}:{email.date}"
        hash_val = hashlib.md5(content.encode()).hexdigest()[:16]
        return f"email:generated:{hash_val}"
    
    def _get_person_id(self, email_address: str) -> str:
        """Get unique ID for person entity.
        
        Args:
            email_address: Email address
        
        Returns:
            Entity ID for the person
        """
        # Normalize email address
        email_lower = email_address.lower().strip()
        return f"person:{email_lower}"
