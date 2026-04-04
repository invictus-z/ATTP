declare global {
  interface Window {
    filterSessions: (event: any) => void;
    lucide: any;
    toggleNodes: () => void;
    showTraceTimeline: () => void;
    closeTraceTimeline: () => void;
    switchPage: (targetViewId: string, clickedBtnId: string) => void;
    closeAllDropdowns: (event?: any) => void;
    toggleMenu: (event: any, menuId: string) => void;
    showFlowDiagram: (event: any) => void;
    closeFlowDiagram: () => void;
    exportTraceReport: (event: any) => void;
    deleteSession: (event: any, btnElement: any) => void;
    unpinSession: (event: any, btnElement: any) => void;
    closeTraceModal: () => void;
    pinSession?: (event: any, btnElement: any) => void;
  }
}
export {};
