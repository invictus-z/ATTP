import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/home' },
    { path: '/home', name: 'home', component: () => import('./views/HomeView.vue') },
    { path: '/node/:index?', name: 'node', component: () => import('./views/NodeView.vue') },
    { path: '/sessions', name: 'sessions', component: () => import('./views/SessionsView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/trace', redirect: (to) => ({ path: '/trace/query', query: to.query }) },
    { path: '/trace/nodes', name: 'trace-nodes', component: () => import('./views/trace/NodeManageView.vue') },
    { path: '/trace/query', name: 'trace-query', component: () => import('./views/trace/TraceQueryView.vue') },
    { path: '/trace/malicious', name: 'trace-malicious', component: () => import('./views/trace/MaliciousView.vue') },
    { path: '/tools', name: 'tools', component: () => import('./views/ToolView.vue') },
    { path: '/user-config', name: 'user-config', component: () => import('./views/UserConfigView.vue') },
  ],
})

router.afterEach((to: RouteLocationNormalized) => {
  if (to.name === 'settings') {
    // Trigger settings load after navigation
    window.dispatchEvent(new CustomEvent('load-settings'))
  }
})

export default router