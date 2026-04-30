import React, { useState, useEffect } from 'react';

interface UpdateInfo {
  version: string;
  releaseDate?: string;
  releaseNotes?: string;
}

interface UpdateProgress {
  percent: number;
  transferred: number;
  total: number;
}

export const UpdateNotification: React.FC = () => {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<UpdateProgress | null>(null);
  const [updateDownloaded, setUpdateDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    // Register update event listeners
    if (window.mailknowAPI) {
      window.mailknowAPI.onUpdateChecking(() => {
        setChecking(true);
        setError(null);
      });

      window.mailknowAPI.onUpdateAvailable((info: UpdateInfo) => {
        setChecking(false);
        setUpdateAvailable(true);
        setUpdateInfo(info);
      });

      window.mailknowAPI.onUpdateNotAvailable(() => {
        setChecking(false);
      });

      window.mailknowAPI.onUpdateProgress((progress: UpdateProgress) => {
        setDownloadProgress(progress);
      });

      window.mailknowAPI.onUpdateDownloaded((info: UpdateInfo) => {
        setDownloading(false);
        setUpdateDownloaded(true);
        setUpdateInfo(info);
      });

      window.mailknowAPI.onUpdateError((err: any) => {
        setChecking(false);
        setDownloading(false);
        setError(err.error || '更新失败');
      });
    }
  }, []);

  const handleCheckUpdate = async () => {
    if (!window.mailknowAPI) return;
    setChecking(true);
    setError(null);
    try {
      await window.mailknowAPI.checkForUpdate();
    } catch (e) {
      setError('检查更新失败');
      setChecking(false);
    }
  };

  const handleDownloadUpdate = async () => {
    if (!window.mailknowAPI) return;
    setDownloading(true);
    setError(null);
    try {
      await window.mailknowAPI.downloadUpdate();
    } catch (e) {
      setError('下载更新失败');
      setDownloading(false);
    }
  };

  const handleInstallUpdate = () => {
    if (!window.mailknowAPI) return;
    window.mailknowAPI.installUpdate();
  };

  if (!window.mailknowAPI) {
    return null;
  }

  return (
    <div className="update-notification">
      {checking && (
        <div className="update-checking">
          <span className="spinner">🔄</span> 检查更新中...
        </div>
      )}

      {error && (
        <div className="update-error">
          <span>❌</span> {error}
          <button onClick={handleCheckUpdate}>重试</button>
        </div>
      )}

      {updateAvailable && !downloading && !updateDownloaded && (
        <div className="update-available">
          <div className="update-info">
            <span>🎉</span> 新版本 {updateInfo?.version} 可用
            {updateInfo?.releaseNotes && (
              <p className="release-notes">{updateInfo.releaseNotes}</p>
            )}
          </div>
          <div className="update-actions">
            <button className="btn-primary" onClick={handleDownloadUpdate}>
              下载更新
            </button>
            <button className="btn-secondary" onClick={() => setUpdateAvailable(false)}>
              稍后提醒
            </button>
          </div>
        </div>
      )}

      {downloading && (
        <div className="update-downloading">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${downloadProgress?.percent || 0}%` }}
            />
          </div>
          <span>
            下载中... {downloadProgress?.percent?.toFixed(1) || 0}%
          </span>
        </div>
      )}

      {updateDownloaded && (
        <div className="update-downloaded">
          <span>✅</span> 更新已就绪，需要重启应用
          <button className="btn-primary" onClick={handleInstallUpdate}>
            立即重启安装
          </button>
        </div>
      )}

      <style>{`
        .update-notification {
          position: fixed;
          bottom: 20px;
          right: 20px;
          z-index: 10000;
          max-width: 360px;
          background: #2a2a3e;
          border-radius: 12px;
          padding: 16px;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          color: #fff;
        }

        .update-checking {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .spinner {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        .update-available {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .update-info {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .release-notes {
          font-size: 12px;
          color: #aaa;
          margin: 4px 0;
        }

        .update-actions {
          display: flex;
          gap: 8px;
        }

        .btn-primary {
          background: #4a9eff;
          color: #fff;
          border: none;
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 14px;
        }

        .btn-primary:hover {
          background: #3a8eef;
        }

        .btn-secondary {
          background: #3a3a4e;
          color: #fff;
          border: none;
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 14px;
        }

        .btn-secondary:hover {
          background: #4a4a5e;
        }

        .progress-bar {
          width: 100%;
          height: 8px;
          background: #3a3a4e;
          border-radius: 4px;
          overflow: hidden;
          margin-bottom: 8px;
        }

        .progress-fill {
          height: 100%;
          background: linear-gradient(90deg, #4a9eff, #6ab0ff);
          transition: width 0.3s ease;
        }

        .update-error {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #ff6b6b;
        }
      `}</style>
    </div>
  );
};
