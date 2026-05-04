"""Tier 2 link extractor - content pattern matching.

Extracts relationships from email content:
- @mentions (person mentions)
- Email addresses
- URLs
- Project names (customizable patterns)
"""

import logging
import re
from typing import List, Set
from urllib.parse import urlparse

from sync.models import Email

from .models import Link, LinkRelation, LinkTier

logger = logging.getLogger(__name__)


class Tier2Extractor:
    """Extract Tier 2 links from email content.

    Tier 2 = 0 token, pattern-based matching from email body.
    """

    # Regex patterns
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    )

    URL_PATTERN = re.compile(
        r'https?://[^\s<>"{}|\\^`\[\]]+'
    )

    # Chinese name pattern (simplified)
    # Matches patterns like @张三 or @李四
    MENTION_PATTERN = re.compile(
        r'@[\u4e00-\u9fa5]{2,4}'
    )

    # Project name patterns (can be customized)
    # Matches patterns like #项目名 or [项目名]
    PROJECT_PATTERN = re.compile(
        r'(?:#|\[)([\u4e00-\u9fa5\w]{2,20})(?:\]|)'
    )

    def __init__(self, custom_project_patterns: List[str] = None):
        """Initialize Tier 2 extractor.

        Args:
            custom_project_patterns: Additional project name patterns
        """
        self.custom_project_patterns = custom_project_patterns or []

    def extract(self, email: Email) -> List[Link]:
        """Extract all Tier 2 links from an email.

        Args:
            email: Email to extract links from

        Returns:
            List of extracted links
        """
        links = []
        email_id = self._get_email_id(email)

        # Combine text and HTML content
        content = self._get_combined_content(email)

        # Extract different types of links
        links.extend(self._extract_mentions(email_id, content))
        links.extend(self._extract_emails(email_id, content, email))
        links.extend(self._extract_urls(email_id, content))
        links.extend(self._extract_projects(email_id, content))

        # Deduplicate
        links = self._deduplicate_links(links)

        logger.info(f"Extracted {len(links)} Tier 2 links from email {email_id}")
        return links

    def _get_combined_content(self, email: Email) -> str:
        """Combine text and HTML content for extraction."""
        parts = []
        if email.text_body:
            parts.append(email.text_body)
        if email.html_body:
            # Remove HTML tags for pattern matching
            clean_html = re.sub(r'<[^>]+>', ' ', email.html_body)
            parts.append(clean_html)
        return ' '.join(parts)

    def _get_email_id(self, email: Email) -> str:
        """Get unique ID for email."""
        if email.message_id:
            msg_id = email.message_id.strip('<>')
            return f"email:{msg_id}"
        return f"email:unknown:{id(email)}"

    def _extract_mentions(self, email_id: str, content: str) -> List[Link]:
        """Extract @mentions from content."""
        links = []
        matches = self.MENTION_PATTERN.findall(content)

        for match in matches:
            # Extract name without @
            name = match[1:]  # Remove @
            person_id = f"person:mentioned:{name}"

            links.append(Link(
                source_id=email_id,
                target_id=person_id,
                relation=LinkRelation.MENTIONS,
                tier=LinkTier.TIER_2,
                weight=0.6,
                metadata={
                    "type": "mention",
                    "name": name,
                    "pattern": match
                }
            ))

        return links

    def _extract_emails(
        self,
        email_id: str,
        content: str,
        email: Email
    ) -> List[Link]:
        """Extract email addresses from content."""
        links = []
        matches = self.EMAIL_PATTERN.findall(content)

        # Get already known addresses
        known_addresses = set()
        if email.from_addr:
            known_addresses.add(email.from_addr.address.lower())
        for addr in email.to_addrs:
            known_addresses.add(addr.address.lower())
        for addr in email.cc_addrs:
            known_addresses.add(addr.address.lower())

        for match in matches:
            # Skip if already in To/Cc
            if match.lower() in known_addresses:
                continue

            person_id = f"person:{match.lower()}"

            links.append(Link(
                source_id=email_id,
                target_id=person_id,
                relation=LinkRelation.MENTIONS,
                tier=LinkTier.TIER_2,
                weight=0.7,
                metadata={
                    "type": "email_in_content",
                    "email": match
                }
            ))

        return links

    def _extract_urls(self, email_id: str, content: str) -> List[Link]:
        """Extract URLs from content."""
        links = []
        matches = self.URL_PATTERN.findall(content)

        for url in matches:
            # Parse URL to extract domain
            try:
                parsed = urlparse(url)
                domain = parsed.netloc

                # Create entity ID for the URL/domain
                url_id = f"url:{domain}"

                links.append(Link(
                    source_id=email_id,
                    target_id=url_id,
                    relation=LinkRelation.RELATED_TO,
                    tier=LinkTier.TIER_2,
                    weight=0.5,
                    metadata={
                        "type": "url",
                        "url": url,
                        "domain": domain
                    }
                ))
            except Exception as e:
                logger.debug(f"Failed to parse URL {url}: {e}")

        return links

    def _extract_projects(self, email_id: str, content: str) -> List[Link]:
        """Extract project names from content."""
        links = []
        matches = self.PROJECT_PATTERN.findall(content)

        for project_name in matches:
            project_id = f"project:{project_name}"

            links.append(Link(
                source_id=email_id,
                target_id=project_id,
                relation=LinkRelation.BELONGS_TO,
                tier=LinkTier.TIER_2,
                weight=0.8,
                metadata={
                    "type": "project",
                    "name": project_name
                }
            ))

        return links

    def _deduplicate_links(self, links: List[Link]) -> List[Link]:
        """Remove duplicate links."""
        seen = set()
        unique_links = []

        for link in links:
            if link.id not in seen:
                seen.add(link.id)
                unique_links.append(link)

        return unique_links
