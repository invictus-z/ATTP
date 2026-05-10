/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare global {
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