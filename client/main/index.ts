import { app, BrowserWindow, ipcMain, dialog, Notification } from 'electron';
import { autoUpdater, UpdateInfo } from 'electron-updater';
import * as path from 'path';
import * as fs from 'fs';
import { spawn, ChildProcess } from 'child_process';

let mainWindow: BrowserWindow | null = null;
let backendProcess: ChildProcess | null = null;

// ===== Auto Updater Configuration =====
autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = true;
autoUpdater.setFeedURL({
  provider: 'github',
  owner: 'mailknow',
  repo: 'mailknow-releases'
});

// ===== Backend Process Management =====
function startBackend() {
  const backendPath = getBackendPath();
  if (!backendPath || !fs.existsSync(backendPath)) {
    console.log('Backend not found, skipping...');
    console.log('Note: Windows version requires Python to be installed for backend functionality.');
    return;
  }

  // Start Python backend
  const { spawn } = require('child_process');
  
  let proc;
  if (process.platform === 'win32' && backendPath.endsWith('.py')) {
    // Windows: run Python script
    const pythonExe = getPythonExecutable();
    proc = spawn(pythonExe, [backendPath], {
      cwd: path.dirname(backendPath),
      stdio: 'inherit'
    });
  } else {
    // macOS/Linux: run executable directly
    proc = spawn(backendPath, [], {
      cwd: path.dirname(backendPath),
      stdio: 'inherit'
    });
  }
  
  backendProcess = proc;

  proc.on('error', (err: Error) => {
    console.error('Backend process error:', err);
  });

  proc.on('exit', (code: number) => {
    console.log(`Backend process exited with code ${code}`);
    backendProcess = null;
  });
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

function getBackendPath(): string {
  const platform = process.platform;
  const isDev = !app.isPackaged;

  if (isDev) {
    // Development: use Python directly
    return path.join(__dirname, '../../../src/api/server.py');
  }

  // Production: use bundled backend
  const resourcesPath = process.resourcesPath;
  if (platform === 'darwin') {
    // macOS: use bundled executable
    const execPath = path.join(resourcesPath, 'backend', 'mailknow');
    if (fs.existsSync(execPath)) return execPath;
    // Fallback: use Python source
    return path.join(resourcesPath, 'backend', 'src/api/server.py');
  } else if (platform === 'win32') {
    // Windows: check for exe first, then Python source
    const execPath = path.join(resourcesPath, 'backend', 'mailknow.exe');
    if (fs.existsSync(execPath)) return execPath;
    // Fallback: use Python source (requires Python installed)
    const pyPath = path.join(resourcesPath, 'backend', 'src/api/server.py');
    if (fs.existsSync(pyPath)) {
      // Return python command with script path
      return pyPath;
    }
    // No backend available
    return '';
  } else {
    return path.join(resourcesPath, 'backend', 'mailknow');
  }
}

function getPythonExecutable(): string {
  // Find Python executable on Windows
  const possiblePaths = [
    'python',
    'python3',
    'C:\\Python311\\python.exe',
    'C:\\Python310\\python.exe',
    'C:\\Python39\\python.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'),
  ];
  
  for (const p of possiblePaths) {
    if (p && fs.existsSync(p)) return p;
  }
  return 'python';
}

// ===== IPC Handlers =====

// Email list handler
ipcMain.handle('email:list', async (_event, args) => {
  const { folder = 'INBOX', page = 1, pageSize = 50, gateClass } = args || {};
  const mockEmails = generateMockEmails(pageSize, gateClass);
  return {
    emails: mockEmails,
    total: 1250,
    page,
    pageSize,
  };
});

// Email detail handler
ipcMain.handle('email:detail', async (_event, emailId: string) => {
  return {
    id: emailId,
    subject: '项目进度讨论',
    from: { name: '张三', address: 'zhangsan@company.com' },
    to: [{ name: '我', address: 'me@company.com' }],
    cc: [],
    date: new Date().toISOString(),
    body: '我们讨论一下项目的下一步计划，请查看附件中的进度报告。',
    gateClass: 'routine',
    isRead: false,
  };
});

// Email gate classify handler
ipcMain.handle('email:classify', async (_event, emailId: string) => {
  return {
    emailId,
    gateClass: 'routine',
    confidence: 0.85,
    matchedRules: ['to_me'],
  };
});

// Account management handlers
ipcMain.handle('account:list', async () => {
  return { accounts: [] };
});

ipcMain.handle('account:add', async (_event, account) => {
  return { success: true, accountId: 'acc_' + Date.now() };
});

ipcMain.handle('account:remove', async (_event, accountId: string) => {
  return { success: true };
});

// Sync handlers
ipcMain.handle('sync:start', async (_event, accountId: string) => {
  return { success: true, message: 'Sync started' };
});

ipcMain.handle('sync:status', async () => {
  return {
    accounts: [],
    isRunning: false,
    lastSync: null,
  };
});

// Search handler
ipcMain.handle('search:query', async (_event, args) => {
  const { query, page = 1, pageSize = 20 } = args || {};
  return {
    results: [],
    total: 0,
    page,
    pageSize,
  };
});

// Gate stats handler
ipcMain.handle('gate:stats', async () => {
  return {
    spam: 150,
    routine: 850,
    important: 180,
    urgent: 20,
    notification: 50,
  };
});

// Token budget handlers
ipcMain.handle('token:usage', async () => {
  return {
    dailyUsed: 15000,
    dailyLimit: 100000,
    monthlyUsed: 450000,
    monthlyLimit: 1000000,
    level: 'normal',
  };
});

ipcMain.handle('token:budget', async (_event, config) => {
  return { success: true, config };
});

// ===== Auto Update IPC Handlers =====
ipcMain.handle('update:check', async () => {
  try {
    const result = await autoUpdater.checkForUpdates();
    return {
      available: result?.updateInfo?.version !== app.getVersion(),
      version: result?.updateInfo?.version,
      releaseDate: result?.updateInfo?.releaseDate,
      releaseNotes: result?.updateInfo?.releaseNotes,
    };
  } catch (error) {
    console.error('Update check failed:', error);
    return { available: false, error: String(error) };
  }
});

ipcMain.handle('update:download', async () => {
  try {
    await autoUpdater.downloadUpdate();
    return { success: true };
  } catch (error) {
    console.error('Update download failed:', error);
    return { success: false, error: String(error) };
  }
});

ipcMain.handle('update:install', () => {
  autoUpdater.quitAndInstall(false, true);
});

ipcMain.handle('app:version', () => {
  return {
    version: app.getVersion(),
    name: app.getName(),
    platform: process.platform,
    arch: process.arch,
  };
});

// ===== Auto Updater Events =====
autoUpdater.on('checking-for-update', () => {
  console.log('Checking for update...');
  sendToRenderer('update:checking');
});

autoUpdater.on('update-available', (info: UpdateInfo) => {
  console.log('Update available:', info.version);
  sendToRenderer('update:available', info);
});

autoUpdater.on('update-not-available', (info: UpdateInfo) => {
  console.log('Update not available:', info.version);
  sendToRenderer('update:not-available', info);
});

autoUpdater.on('download-progress', (progress) => {
  console.log(`Download progress: ${progress.percent}%`);
  sendToRenderer('update:progress', {
    percent: progress.percent,
    transferred: progress.transferred,
    total: progress.total,
  });
});

autoUpdater.on('update-downloaded', (info: UpdateInfo) => {
  console.log('Update downloaded:', info.version);
  sendToRenderer('update:downloaded', info);

  // Show notification
  if (Notification.isSupported()) {
    new Notification({
      title: 'MailKnow 更新已就绪',
      body: `新版本 ${info.version} 已下载，点击重启安装`,
    }).show();
  }
});

autoUpdater.on('error', (error) => {
  console.error('Auto updater error:', error);
  sendToRenderer('update:error', { error: String(error) });
});

function sendToRenderer(channel: string, data?: any) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data);
  }
}

// ===== Mock Data Generator =====
function generateMockEmails(count: number, gateClass?: string) {
  const gateClasses = ['spam', 'routine', 'important', 'urgent', 'notification'];
  const senders = ['张三', '李四', '王五', '赵六', '系统通知', 'HR部门', '财务部'];
  const subjects = [
    '项目进度讨论',
    '周报提交提醒',
    '会议邀请',
    '审批请求',
    '系统维护通知',
    '报销审批',
    '合同签署',
  ];

  return Array.from({ length: count }, (_, i) => ({
    id: `email_${Date.now()}_${i}`,
    subject: subjects[Math.floor(Math.random() * subjects.length)],
    from: {
      name: senders[Math.floor(Math.random() * senders.length)],
      address: `sender${i}@company.com`,
    },
    date: new Date(Date.now() - Math.random() * 7 * 24 * 60 * 60 * 1000).toISOString(),
    gateClass: gateClass || gateClasses[Math.floor(Math.random() * gateClasses.length)],
    isRead: Math.random() > 0.5,
    hasAttachment: Math.random() > 0.7,
  }));
}

// ===== Window Creation =====
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, '../preload/index.js'),
    },
    title: 'MailKnow',
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#1a1a2e',
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Check for updates after window is ready
  if (!process.env.NODE_ENV) {
    setTimeout(() => {
      autoUpdater.checkForUpdates().catch(console.error);
    }, 3000);
  }
}

// ===== App Lifecycle =====
app.whenReady().then(() => {
  startBackend();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackend();
});

// Single instance lock
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}
