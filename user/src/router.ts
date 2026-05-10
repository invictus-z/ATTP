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
  ],
})

router.afterEach((to: RouteLocationNormalized) => {
  if (to.name === 'settings') {
    // Trigger settings load after navigation
    window.dispatchEvent(new CustomEvent('load-settings'))
  }
})

export default router