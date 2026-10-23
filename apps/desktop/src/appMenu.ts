import { BrowserWindow, Menu, ipcMain, type MenuItemConstructorOptions } from 'electron';
export function registerAppMenu(isTrusted: (event: Electron.IpcMainInvokeEvent) => boolean) {
  ipcMain.handle('window:app-menu', (event, menu: unknown) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!window || !isTrusted(event) || typeof menu !== 'string') return null;
    return new Promise<string | null>(resolve => {
      let action: string | null = null;
      const item = (label: string, id: string): MenuItemConstructorOptions => ({ label, click: () => { action = id; } });
      const history = (label: string, redo = false): MenuItemConstructorOptions => ({ label, click: () => {
        const modifiers: Array<'meta' | 'control' | 'shift'> = [process.platform === 'darwin' ? 'meta' : 'control'];
        if (redo) modifiers.push('shift');
        window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Z', modifiers });
        window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Z', modifiers });
      } });
      const menus: Record<string, MenuItemConstructorOptions[]> = {
        file: [item('新建项目', 'new'), item('打开项目列表', 'projects'), item('添加资料…', 'import'), {type:'separator'}, item('打开数据文件夹', 'folder'), item('设置', 'settings'), {type:'separator'}, {role:'quit',label:'退出'}],
        edit: [history('撤销'), history('重做', true), {type:'separator'}, {role:'cut',label:'剪切'}, {role:'copy',label:'复制'}, {role:'paste',label:'粘贴'}, {role:'selectAll',label:'全选'}],
        view: [item('首页', 'home'), item('正在运行的任务', 'tasks'), {type:'separator'}, {role:'zoomIn',label:'放大'}, {role:'zoomOut',label:'缩小'}, {role:'resetZoom',label:'重置缩放'}, {role:'togglefullscreen',label:'切换全屏'}],
        help: [item('使用说明', 'help'), item('关于 MxinspireX', 'about')],
      };
      if (!menus[menu]) { resolve(null); return; }
      Menu.buildFromTemplate(menus[menu]).popup({ window, callback: () => resolve(action) });
    });
  });
}
