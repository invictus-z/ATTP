/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare global {
  // 构建期由 vite define 注入（见 vite.config.ts），等于 package.json 的 version
  const __APP_VERSION__: string;
  interface Window {
    electronAPI: {
      platform: string;
      isElectron: boolean;
      request: (url: string, options?: any) => Promise<any>;
      wsConnect: (url: string) => Promise<any>;
      wsSend: (id: string, data: any) => void;
      wsClose: (id: string) => Promise<{ ok: boolean }>;
      onWsMessage: (cb: (data: any) => void) => void;
      onWsOpen: (cb: (data: any) => void) => void;
      onWsClose: (cb: (data: any) => void) => void;
      onWsError: (cb: (data: any) => void) => void;
    };
  }
}

export {}