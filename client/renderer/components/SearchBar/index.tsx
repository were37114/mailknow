/**
 * SearchBar - 搜索框组件
 * 
 * 支持：
 * - 关键词搜索
 * - 自然语言查询（NL→SQL）
 * - 实体搜索（"和张三往来的邮件"）
 * - 搜索历史
 */

import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';

// ===== Types =====

export interface SearchResult {
  email_id: string;
  subject: string;
  sender: string;
  sender_name?: string;
  preview: string;
  date: string;
  score: number;
  highlights?: {
    subject?: [number, number][];
    content?: [number, number][];
  };
}

export interface SearchBarProps {
  onSearch: (query: string) => Promise<SearchResult[]>;
  onResultClick: (result: SearchResult) => void;
  placeholder?: string;
  recentQueries?: string[];
  maxResults?: number;
}

// ===== Search History Item =====

interface SearchHistoryProps {
  queries: string[];
  onSelect: (query: string) => void;
  onClear: () => void;
}

const SearchHistory: React.FC<SearchHistoryProps> = ({ queries, onSelect, onClear }) => {
  if (queries.length === 0) return null;

  return (
    <div className="search-history">
      <div className="history-header">
        <span className="history-title">最近搜索</span>
        <button className="btn-clear-history" onClick={onClear}>
          清空
        </button>
      </div>
      <div className="history-list">
        {queries.slice(0, 5).map((query, index) => (
          <button
            key={index}
            className="history-item"
            onClick={() => onSelect(query)}
          >
            🔍 {query}
          </button>
        ))}
      </div>
    </div>
  );
};

// ===== Search Result Item =====

interface SearchResultItemProps {
  result: SearchResult;
  onClick: () => void;
}

const SearchResultItem: React.FC<SearchResultItemProps> = ({ result, onClick }) => {
  const scoreBadge = useMemo(() => {
    if (result.score >= 0.8) return { label: '高相关', className: 'score-high' };
    if (result.score >= 0.5) return { label: '相关', className: 'score-medium' };
    return { label: '可能相关', className: 'score-low' };
  }, [result.score]);

  return (
    <div className="search-result-item" onClick={onClick}>
      <div className="result-score">
        <span className={`score-badge ${scoreBadge.className}`}>
          {(result.score * 100).toFixed(0)}%
        </span>
      </div>

      <div className="result-content">
        <div className="result-header">
          <span className="result-subject" title={result.subject}>
            {result.subject}
          </span>
        </div>
        
        <div className="result-meta">
          <span className="result-sender">
            {result.sender_name || result.sender.split('@')[0]}
          </span>
          <span className="result-date">
            {new Date(result.date).toLocaleDateString('zh-CN')}
          </span>
        </div>

        <div className="result-preview" title={result.preview}>
          {result.preview}
        </div>
      </div>
    </div>
  );
};

// ===== Search Suggestion =====

interface SearchSuggestionProps {
  query: string;
  onSelect: (suggestion: string) => void;
}

const SearchSuggestions: React.FC<SearchSuggestionProps> = ({ query, onSelect }) => {
  const suggestions = useMemo(() => {
    const lower = query.toLowerCase();
    
    // 检测是否为实体查询
    if (lower.includes('往来') || lower.includes('来自') || lower.includes('发给')) {
      return [
        `和${extractEntity(query)}往来的邮件`,
        `${extractEntity(query)}发给我的邮件`,
        `我发给${extractEntity(query)}的邮件`,
      ];
    }

    // 检测是否为时间范围查询
    if (lower.includes('最近') || lower.includes('本周') || lower.includes('本月')) {
      return [
        query,
        `${query}重要邮件`,
        `${query}审批邮件`,
      ];
    }

    return [];
  }, [query]);

  if (suggestions.length === 0) return null;

  return (
    <div className="search-suggestions">
      {suggestions.map((suggestion, index) => (
        <button
          key={index}
          className="suggestion-item"
          onClick={() => onSelect(suggestion)}
        >
          💡 {suggestion}
        </button>
      ))}
    </div>
  );
};

function extractEntity(query: string): string {
  // 简单实体提取
  const match = query.match(/和(.+?)(往来|往来邮件|的邮件)/);
  if (match) return match[1];
  
  const match2 = query.match(/(.+?)(发给我|发来的|的)/);
  if (match2) return match2[1];
  
  return query;
}

// ===== Search Bar Component =====

export const SearchBar: React.FC<SearchBarProps> = ({
  onSearch,
  onResultClick,
  placeholder = '搜索邮件，如"和张三往来的邮件"',
  recentQueries = [],
  maxResults = 20,
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  // 搜索防抖
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setShowResults(false);
      return;
    }

    const timer = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const searchResults = await onSearch(query);
        setResults(searchResults.slice(0, maxResults));
        setShowResults(true);
      } catch (err) {
        setError('搜索失败，请重试');
        console.error('Search error:', err);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, onSearch, maxResults]);

  // 点击外部关闭
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (resultsRef.current && !resultsRef.current.contains(event.target as Node)) {
        setShowResults(false);
        setShowHistory(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleFocus = useCallback(() => {
    if (query.trim() === '' && recentQueries.length > 0) {
      setShowHistory(true);
    }
  }, [query, recentQueries]);

  const handleHistorySelect = useCallback((historyQuery: string) => {
    setQuery(historyQuery);
    setShowHistory(false);
    inputRef.current?.focus();
  }, []);

  const handleClearHistory = useCallback(() => {
    setShowHistory(false);
  }, []);

  const handleResultSelect = useCallback((result: SearchResult) => {
    onResultClick(result);
    setShowResults(false);
  }, [onResultClick]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowResults(false);
      setShowHistory(false);
      inputRef.current?.blur();
    }
  }, []);

  return (
    <div className="search-bar-wrapper" ref={resultsRef}>
      {/* Search Input */}
      <div className="search-input-wrapper">
        <span className="search-icon">🔍</span>
        <input
          ref={inputRef}
          type="text"
          className="search-input"
          placeholder={placeholder}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
        />
        {loading && <span className="search-loading">搜索中...</span>}
        {query && (
          <button
            className="btn-clear"
            onClick={() => {
              setQuery('');
              inputRef.current?.focus();
            }}
          >
            ✕
          </button>
        )}
      </div>

      {/* Search History */}
      {showHistory && !showResults && (
        <SearchHistory
          queries={recentQueries}
          onSelect={handleHistorySelect}
          onClear={handleClearHistory}
        />
      )}

      {/* Search Suggestions */}
      {!showResults && query && !loading && (
        <SearchSuggestions
          query={query}
          onSelect={handleHistorySelect}
        />
      )}

      {/* Search Results */}
      {showResults && (
        <div className="search-results">
          {error && (
            <div className="search-error">
              <p>❌ {error}</p>
            </div>
          )}

          {!error && results.length === 0 && !loading && (
            <div className="search-empty">
              <p>未找到相关邮件</p>
              <p className="search-tip">💡 试试"和某人往来的邮件"</p>
            </div>
          )}

          {!error && results.length > 0 && (
            <>
              <div className="results-header">
                <span>找到 {results.length} 封相关邮件</span>
              </div>
              <div className="results-list">
                {results.map((result) => (
                  <SearchResultItem
                    key={result.email_id}
                    result={result}
                    onClick={() => handleResultSelect(result)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default SearchBar;
