import { contextBridge, ipcRenderer } from 'electron';

// Expose protected API to renderer
contextBridge.exposeInMainWorld('mailknowAPI', {
  // Email operations
  listEmails: (args?: { folder?: string; page?: number; pageSize?: number; gateClass?: string }) =>
    ipcRenderer.invoke('email:list', args),

  getEmail: (emailId: string) =>
    ipcRenderer.invoke('email:detail', emailId),

  classifyEmail: (emailId: string) =>
    ipcRenderer.invoke('email:classify', emailId),

  // Account operations
  listAccounts: () =>
    ipcRenderer.invoke('account:list'),

  addAccount: (account: { email: string; password: string; provider?: string }) =>
    ipcRenderer.invoke('account:add', account),

  removeAccount: (accountId: string) =>
    ipcRenderer.invoke('account:remove', accountId),

  // Sync operations
  startSync: (accountId: string) =>
    ipcRenderer.invoke('sync:start', accountId),

  getSyncStatus: () =>
    ipcRenderer.invoke('sync:status'),

  // Search
  search: (args: { query: string; page?: number; pageSize?: number }) =>
    ipcRenderer.invoke('search:query', args),

  // Gate stats
  getGateStats: () =>
    ipcRenderer.invoke('gate:stats'),

  // Token budget
  getTokenUsage: () =>
    ipcRenderer.invoke('token:usage'),

  setTokenBudget: (config: { dailyLimit?: number; monthlyLimit?: number; dailyCostLimit?: number; monthlyCostLimit?: number }) =>
    ipcRenderer.invoke('token:budget', config),

  // ===== Auto Update API =====
  checkForUpdate: () =>
    ipcRenderer.invoke('update:check'),

  downloadUpdate: () =>
    ipcRenderer.invoke('update:download'),

  installUpdate: () =>
    ipcRenderer.invoke('update:install'),

  getAppVersion: () =>
    ipcRenderer.invoke('app:version'),

  // Update event listeners
  onUpdateChecking: (callback: () => void) => {
    ipcRenderer.on('update:checking', () => callback());
  },

  onUpdateAvailable: (callback: (info: any) => void) => {
    ipcRenderer.on('update:available', (_event, info) => callback(info));
  },

  onUpdateNotAvailable: (callback: (info: any) => void) => {
    ipcRenderer.on('update:not-available', (_event, info) => callback(info));
  },

  onUpdateProgress: (callback: (progress: { percent: number; transferred: number; total: number }) => void) => {
    ipcRenderer.on('update:progress', (_event, progress) => callback(progress));
  },

  onUpdateDownloaded: (callback: (info: any) => void) => {
    ipcRenderer.on('update:downloaded', (_event, info) => callback(info));
  },

  onUpdateError: (callback: (error: any) => void) => {
    ipcRenderer.on('update:error', (_event, error) => callback(error));
  },

  // ===== Event listeners (existing) =====
  onSyncProgress: (callback: (progress: any) => void) => {
    ipcRenderer.on('sync:progress', (_event, data) => callback(data));
  },

  onNewEmail: (callback: (email: any) => void) => {
    ipcRenderer.on('email:new', (_event, data) => callback(data));
  },

  // Cleanup listeners
  removeAllListeners: (channel: string) => {
    ipcRenderer.removeAllListeners(channel);
  },
});