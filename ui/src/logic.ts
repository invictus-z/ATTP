let currentTraceData: any[] = [];
let currentTracePage = 0;
const TRACE_ITEMS_PER_PAGE = 2; // Number of items per page

function renderTracePage(animateOut = false) {
    const container = document.getElementById('trace-timeline-container');
    const pagination = document.getElementById('trace-pagination');
    const pageInfo = document.getElementById('trace-page-info');
    const prevBtn = document.getElementById('trace-prev-btn') as HTMLButtonElement;
    const nextBtn = document.getElementById('trace-next-btn') as HTMLButtonElement;
    
    if (!container || !pagination) return;

    const totalPages = Math.ceil(currentTraceData.length / TRACE_ITEMS_PER_PAGE);
    
    if (totalPages <= 1) {
        pagination.classList.add('hidden');
    } else {
        pagination.classList.remove('hidden');
        if (pageInfo) pageInfo.innerText = `Page ${currentTracePage + 1} / ${totalPages}`;
        if (prevBtn) prevBtn.disabled = currentTracePage === 0;
        if (nextBtn) nextBtn.disabled = currentTracePage >= totalPages - 1;
    }

    const doRender = () => {
        container.innerHTML = '<div class="absolute left-4 top-2 bottom-2 w-px bg-gray-200 border-l border-dashed border-gray-300 z-0"></div>';
        
        const startIdx = currentTracePage * TRACE_ITEMS_PER_PAGE;
        const endIdx = Math.min(startIdx + TRACE_ITEMS_PER_PAGE, currentTraceData.length);
        const pageData = currentTraceData.slice(startIdx, endIdx);

        pageData.forEach((hop: any, index: number) => {
            const idx = startIdx + index;
            const log = hop.Log;
            let timeStr = log.Timestamp;
            try {
                const d = new Date(log.Timestamp);
                timeStr = d.toISOString().split('T')[1].replace('Z', '');
            } catch(e){}
            
            let desc = "Transmission";
            if (log.Content_Snapshot && typeof log.Content_Snapshot === 'object') {
                if (log.Content_Snapshot.Action) {
                    desc = `Action: <code class="text-indigo-600">${log.Content_Snapshot.Action}</code>`;
                }
            } else if (typeof log.Content_Snapshot === 'string') {
                desc = log.Content_Snapshot;
            }
            
            let details = `
                <div class="mt-2 space-y-1 bg-white border border-gray-100 rounded p-2 text-[10px] font-mono shadow-sm">
                    <div class="flex"><span class="text-gray-400 w-20 shrink-0">Hash: </span><span class="text-gray-600 truncate" title="${log.Entry_Hash || log.Genesis_Hash}">${log.Entry_Hash || log.Genesis_Hash}</span></div>
                    <div class="flex"><span class="text-gray-400 w-20 shrink-0">Prev: </span><span class="text-gray-600 truncate" title="${log.Prev_Hash}">${log.Prev_Hash}</span></div>
                    <div class="flex"><span class="text-gray-400 w-20 shrink-0">Sig: </span><span class="text-gray-600 truncate" title="${log.Signature}">${log.Signature}</span></div>
                </div>
            `;
            
            const didName = log.node_did.split(':').pop() || "Unknown";

            let senderName = didName;
            let receiverName = "Target";

            const isLastHop = idx === currentTraceData.length - 1;
            const entryHash = log.Entry_Hash || log.Genesis_Hash;
            const childHop = currentTraceData.find((t: any, j: number) => j !== idx && t.Log.Prev_Hash === entryHash);

            if (childHop) {
                // 有子节点：箭头指向子节点（原有逻辑）
                receiverName = childHop.Log.node_did.split(':').pop() || "Unknown";
            } else if (isLastHop && log.target_did) {
                // 最后一个节点且有 target_did：箭头指向 target_did（新逻辑）
                receiverName = log.target_did.split(':').pop() || "Unknown";
            } else {
                // 其他情况：找父节点
                const myPrev = log.Prev_Hash;
                if (myPrev && myPrev !== "Genesis") {
                    const parentHop = currentTraceData.find((t: any) => t.Log.Entry_Hash === myPrev || t.Log.Genesis_Hash === myPrev);
                    if (parentHop) {
                        receiverName = parentHop.Log.node_did.split(':').pop() || "Unknown";
                    }
                }
            }
            
            const traceTitle = `[ ${senderName} -> ${receiverName} ]`;
            
            const stepHtml = `
                  <div class="relative flex gap-4 mb-6 z-10 opacity-0 translate-y-2 transition-all duration-300" style="transition-delay: ${index * 50}ms" id="trace-item-${idx}">
                      <div class="w-8 h-8 rounded-full bg-white border border-gray-200 mt-1 flex items-center justify-center shrink-0 shadow-sm relative z-10">
                          <i data-lucide="${idx === 0 ? 'bot' : 'arrow-right-left'}" class="w-3.5 h-3.5 ${idx === 0 ? 'text-gray-600' : 'text-blue-500'}"></i>
                      </div>
                      <div class="flex-1 min-w-0 overflow-hidden">
                          <div class="flex items-center justify-between mb-1">
                              <span class="text-[13px] font-semibold text-gray-800 truncate" title="${log.node_did}">${traceTitle}</span>
                              <span class="text-[11px] text-gray-400 shrink-0">${timeStr}</span>
                          </div>
                          <div class="text-[12px] text-gray-500 bg-gray-50 px-3 py-2 rounded-lg border border-gray-100">
                              ${desc}
                          </div>
                          ${details}
                      </div>
                  </div>
            `;
            container.insertAdjacentHTML('beforeend', stepHtml);
        });
        
        if (window.lucide) window.lucide.createIcons();

        // Trigger animations
        requestAnimationFrame(() => {
            pageData.forEach((_, index) => {
                const el = document.getElementById(`trace-item-${startIdx + index}`);
                if (el) {
                    el.classList.remove('opacity-0', 'translate-y-2');
                    el.classList.add('opacity-100', 'translate-y-0');
                }
            });
        });
    };

    if (animateOut) {
        const currentItems = container.querySelectorAll('.z-10');
        currentItems.forEach((el, i) => {
            (el as HTMLElement).style.transitionDelay = `${i * 30}ms`;
            el.classList.remove('opacity-100', 'translate-y-0');
            el.classList.add('opacity-0', '-translate-y-2');
        });
        setTimeout(doRender, 200); // Wait for fade out
    } else {
        doRender();
    }
}

// Bind pagination events once
document.addEventListener('DOMContentLoaded', () => {
    // Wait for the modal elements to be rendered by main.ts
    // We can just use event delegation or direct binding if elements exist
});

window.toggleNodes = function () {
  const list = document.getElementById('nodes-list');
  const chevron = document.getElementById('nodes-chevron');
  if (!list || !chevron) return;
  if (list.style.maxHeight === '0px' || list.style.maxHeight === '') {
    list.style.maxHeight = '200px';
    list.style.opacity = '1';
    chevron.style.transform = 'rotate(0deg)';
  } else {
    list.style.maxHeight = '0px';
    list.style.opacity = '0';
    chevron.style.transform = 'rotate(-90deg)';
  }
};

(window as any).showTraceTimeline = async function (sessionId: string) {
  const modal = document.getElementById('trace-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  
  
  const sessionLabel = document.getElementById('trace-session-id-label');
  if (sessionLabel) {
      sessionLabel.innerText = 'ID: ' + sessionId.substring(0, 12) + '...';
  }

  const container = document.getElementById('trace-timeline-container');
  if (container) {
      container.innerHTML = '<div class="text-center text-sm py-4 text-gray-400">Loading trace via ANP...</div>';
  }
  
  // Show modal with animation
  setTimeout(() => {
    modal.classList.remove('opacity-0');
    const content = modal.querySelector('.timeline-content');
    if (content) {
      content.classList.remove('scale-95', 'translate-y-4');
      content.classList.add('scale-100', 'translate-y-0');
    }
  }, 10);
  
  // Fetch real data
  try {
      const res = await fetch(`http://localhost:8001/api/traces/${sessionId}`);
      const data = await res.json();
      if (container) {
          if (!data.Path || data.Path.length === 0) {
              container.innerHTML = '<div class="text-center text-sm py-4 text-gray-400">No traces available for this session.</div>';
              document.getElementById('trace-pagination')?.classList.add('hidden');
              return;
          }
          
          currentTraceData = data.Path;
          currentTracePage = 0;
          renderTracePage(false);
          
          const latencySpan = document.getElementById('trace-latency-value');
          if (latencySpan && data.Path.length > 0) {
              const first = new Date(data.Path[0].Log.Timestamp).getTime() || Date.now();
              const last = new Date(data.Path[data.Path.length - 1].Log.Timestamp).getTime() || Date.now();
              const latency = Math.max(15, Math.abs(last - first)); // ms exact
              latencySpan.innerText = `Total Latency: ${latency}ms`;
          } else if (latencySpan) {
              latencySpan.innerText = `Total Latency: --ms`;
          }
      }
  } catch(e) {
      if (container) {
          container.innerHTML = '<div class="text-center text-sm py-4 text-red-400">Failed to load trace.</div>';
      }
  }
};

window.closeTraceTimeline = function () {
  const modal = document.getElementById('trace-modal');
  if (!modal) return;
  modal.classList.add('opacity-0');
  const content = modal.querySelector('.timeline-content');
  if (content) {
    content.classList.remove('scale-100', 'translate-y-0');
    content.classList.add('scale-95', 'translate-y-4');
  }
  setTimeout(() => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }, 300);
};

(window as any).switchPage = function (targetViewId: string, clickedBtnId: string) {
  document.querySelectorAll('.page-view').forEach(view => {
    view.classList.add('hidden');
  });
  
  const target = document.getElementById(targetViewId);
  if (target) target.classList.remove('hidden');
  if (window.lucide) window.lucide.createIcons();

  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.remove('bg-brand-50', 'text-brand-600');
    btn.classList.add('text-gray-500', 'hover:bg-gray-50', 'hover:text-gray-800');
    const icon = btn.querySelector('i');
    if (icon) {
      icon.classList.remove('opacity-90');
      icon.classList.add('opacity-70');
    }
  });

  const activeBtn = document.getElementById(clickedBtnId);
  if (activeBtn) {
    activeBtn.classList.remove('text-gray-500', 'hover:bg-gray-50', 'hover:text-gray-800');
    activeBtn.classList.add('bg-brand-50', 'text-brand-600');
    const activeIcon = activeBtn.querySelector('i');
    if (activeIcon) {
      activeIcon.classList.remove('opacity-70');
      activeIcon.classList.add('opacity-90');
    }
  }
};

window.closeAllDropdowns = function () {
  const dropdowns = document.querySelectorAll('.dropdown-menu');
  dropdowns.forEach(menu => {
    menu.classList.add('hidden');
    menu.classList.remove('dropdown-open');
  });
};

window.toggleMenu = function (event, menuId) {
  event.stopPropagation();
  document.querySelectorAll('.session-item').forEach(el => {
    (el as HTMLElement).style.zIndex = '1';
  });

  const menu = document.getElementById(menuId);
  if (!menu) return;
  const isHidden = menu.classList.contains('hidden');
  
  window.closeAllDropdowns();

  if (isHidden) {
    const parentItem = menu.closest('.session-item');
    if (parentItem) (parentItem as HTMLElement).style.zIndex = '40';
    menu.classList.remove('hidden');
    menu.classList.add('dropdown-open');
  }
};

window.showFlowDiagram = function (event) {
  event.stopPropagation();
  window.closeAllDropdowns();
  const modal = document.getElementById('flow-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  setTimeout(() => {
    modal.classList.remove('opacity-0');
    const content = modal.querySelector('.flow-content');
    if (content) {
      content.classList.remove('scale-95', 'translate-y-4');
      content.classList.add('scale-100', 'translate-y-0');
    }
  }, 10);
};

window.closeFlowDiagram = function () {
  const modal = document.getElementById('flow-modal');
  if (!modal) return;
  modal.classList.add('opacity-0');
  const content = modal.querySelector('.flow-content');
  if (content) {
    content.classList.remove('scale-100', 'translate-y-0');
    content.classList.add('scale-95', 'translate-y-4');
  }
  setTimeout(() => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }, 300);
};

window.exportTraceReport = function (event) {
  event.stopPropagation();
  window.closeAllDropdowns();
  const toast = document.getElementById('export-toast');
  if (!toast) return;
  toast.classList.remove('opacity-0', 'translate-x-10', 'pointer-events-none');
  toast.classList.add('opacity-100', 'translate-x-0');
  setTimeout(() => {
    toast.classList.remove('opacity-100', 'translate-x-0');
    toast.classList.add('opacity-0', 'translate-x-10', 'pointer-events-none');
  }, 3000);
};

window.deleteSession = function (event, btnElement) {
  event.stopPropagation();
  const sessionItem = btnElement.closest('.session-item') as HTMLElement;
  if (sessionItem) {
    sessionItem.style.opacity = '0';
    sessionItem.style.transform = 'scale(0.95)';
    setTimeout(() => {
      sessionItem.remove();
      // 这里如果需要可以重新算 count
    }, 200);
  }
};

window.unpinSession = function (event, btnElement) {
  event.stopPropagation();
  window.closeAllDropdowns();
  const sessionItem = btnElement.closest('.session-item') as HTMLElement;
  const recentList = document.getElementById('recent-list');
  if (sessionItem && recentList) {
    sessionItem.style.transition = 'all 0.3s ease';
    sessionItem.style.opacity = '0';
    sessionItem.style.transform = 'scale(0.95)';
    setTimeout(() => {
      btnElement.innerHTML = `<i data-lucide="pin" class="w-3.5 h-3.5"></i> 置顶`;
      btnElement.setAttribute('onclick', 'pinSession(event, this)');
      recentList.prepend(sessionItem);
      // @ts-ignore
      if (window.lucide) window.lucide.createIcons();
      setTimeout(() => {
        sessionItem.style.opacity = '1';
        sessionItem.style.transform = 'scale(1)';
      }, 10);
    }, 300);
  }
};

window.pinSession = function (event, btnElement) {
  event.stopPropagation();
  window.closeAllDropdowns();
  const sessionItem = btnElement.closest('.session-item') as HTMLElement;
  const pinnedList = document.getElementById('pinned-list');
  if (sessionItem && pinnedList) {
    sessionItem.style.transition = 'all 0.3s ease';
    sessionItem.style.opacity = '0';
    sessionItem.style.transform = 'scale(0.95)';
    setTimeout(() => {
      btnElement.innerHTML = `<i data-lucide="pin-off" class="w-3.5 h-3.5"></i> 取消置顶`;
      btnElement.setAttribute('onclick', 'unpinSession(event, this)');
      pinnedList.prepend(sessionItem);
      // @ts-ignore
      if (window.lucide) window.lucide.createIcons();
      setTimeout(() => {
        sessionItem.style.opacity = '1';
        sessionItem.style.transform = 'scale(1)';
      }, 10);
    }, 300);
  }
};

export function setupLogic() {
  const prevBtn = document.getElementById('trace-prev-btn');
  const nextBtn = document.getElementById('trace-next-btn');
  if (prevBtn) {
      prevBtn.addEventListener('click', () => {
          if (currentTracePage > 0) {
              currentTracePage--;
              renderTracePage(true);
          }
      });
  }
  if (nextBtn) {
      nextBtn.addEventListener('click', () => {
          const totalPages = Math.ceil(currentTraceData.length / TRACE_ITEMS_PER_PAGE);
          if (currentTracePage < totalPages - 1) {
              currentTracePage++;
              renderTracePage(true);
          }
      });
  }
  // Initialize lucide immediately if it's there
  if (window.lucide) {
    window.lucide.createIcons();
  }

  // Hide all views first just in case
  document.querySelectorAll('.page-view').forEach(el => {
    el.classList.add('hidden');
  });

  // Try to default the page to home exactly like original
  const homeView = document.getElementById('view-home');
  if (homeView) {
    homeView.classList.remove('hidden');
  }

  
  // Also style the sidebar button for home
  const homeBtn = document.getElementById('nav-home');
  if (homeBtn) {
    homeBtn.classList.add('bg-brand-50', 'text-brand-600', 'font-medium');
    homeBtn.classList.remove('text-gray-500', 'hover:bg-gray-50', 'hover:text-gray-900', 'hover:text-gray-800');
    const icon = homeBtn.querySelector('i');
    if (icon) {
      icon.classList.remove('opacity-70');
      icon.classList.add('opacity-90', 'text-brand-600');
    }
  }
}


window.filterSessions = function (event: any) {
  const searchTerm = event.target.value.toLowerCase();
  const sessionItems = document.querySelectorAll('.session-item');
  
  sessionItems.forEach(item => {
    const el = item as HTMLElement;
    const title = el.getAttribute('data-title')?.toLowerCase() || '';
    if (!el.style.transition) {
      el.style.transition = 'all 0.3s ease';
    }
    if (title.includes(searchTerm)) {
      el.style.display = 'flex';
      setTimeout(() => {
        el.style.opacity = '1';
        el.style.transform = 'scale(1)';
      }, 10);
    } else {
      el.style.opacity = '0';
      el.style.transform = 'scale(0.95)';
      setTimeout(() => {
        el.style.display = 'none';
      }, 300);
    }
  });
};


(window as any).renderDynamicNodes = async function() {
    try {
        const res = await fetch('http://localhost:8001/api/nodes');
        const data = await res.json();
        const nodesList = document.getElementById('nodes-list');
        if (!nodesList) return;
        nodesList.innerHTML = '';
        (window as any).agentNodes = data.agents || [];
        
        (window as any).agentNodes.forEach((agent: any, i: number) => {
            const btnId = `nav-node-${i}`;
            const icon = agent.capabilities.includes('data_storage') ? 'database' : (agent.capabilities.includes('security_check') ? 'shield-check' : 'server');
            const statusColor = agent.online ? 'bg-emerald-400' : 'bg-amber-400';
            const statusTitle = agent.online ? 'Online' : 'Offline';

            nodesList.insertAdjacentHTML('beforeend', `
                <button id="${btnId}" onclick="window.openNodeView(${i}, '${btnId}')" class="nav-btn w-full flex items-center px-2.5 py-2 text-[13px] text-gray-500 hover:bg-gray-50 hover:text-gray-800 rounded-lg transition-colors">
                    <i data-lucide="${icon}" class="w-4 h-4 mr-2.5 opacity-70"></i>
                    <span class="flex-1 text-left truncate">${agent.name}</span>
                    <span class="w-1.5 h-1.5 rounded-full ${statusColor}" title="${statusTitle}"></span>
                </button>
            `);
        });
        if (window.lucide) window.lucide.createIcons();
          
          const latencySpan = document.getElementById('trace-latency-value');
          if (latencySpan && data.Path.length > 0) {
              const first = new Date(data.Path[0].Log.Timestamp).getTime() || Date.now();
              const last = new Date(data.Path[data.Path.length - 1].Log.Timestamp).getTime() || Date.now();
              const latency = Math.max(15, Math.abs(last - first)); // ms exact
              latencySpan.innerText = `Total Latency: ${latency}ms`;
          } else if (latencySpan) {
              latencySpan.innerText = `Total Latency: --ms`;
          }
      } catch (e) {
        console.error('Failed to load nodes:', e);
    }
};

(window as any).openNodeView = function(index: number, btnId: string) {
    const agent = (window as any).agentNodes[index];
    if (!agent) return;

    // Clear previous node chats visually when switching, to strictly show only current node interactions
    const nodeMessagesContainer = document.getElementById('node-messages-container');
    if (nodeMessagesContainer) {
        nodeMessagesContainer.innerHTML = '';
        
        // Restore history if exists
          const currentSess = typeof (window as any).getCurrentSession === 'function' ? (window as any).getCurrentSession() : null;
          const history = currentSess?.nodeHistories?.[agent.did] || [];
        if (history.length > 0 && typeof (window as any).renderNodeMessageHtml === 'function') {
            let html = '';
            history.forEach((msg: any) => {
                html += (window as any).renderNodeMessageHtml(msg.role, msg.text, msg.timeStr);
            });
            nodeMessagesContainer.innerHTML = html;
        }
        requestAnimationFrame(() => {
            if (nodeMessagesContainer.parentElement) {
                nodeMessagesContainer.parentElement.scrollTop = nodeMessagesContainer.parentElement.scrollHeight;
            }
        });
    }

    // Update NodeView elements
    const icon = agent.capabilities.includes('data_storage') ? 'database' : (agent.capabilities.includes('security_check') ? 'shield-check' : 'server');
    document.getElementById('node-header-icon')!.innerHTML = `<i data-lucide="${icon}" class="w-6 h-6 text-emerald-600"></i>`;
    document.getElementById('node-header-name')!.innerText = agent.name;
    document.getElementById('node-header-desc')!.innerText = agent.description || '';
    document.getElementById('node-header-did')!.innerText = agent.did;
    document.getElementById('node-header-endpoint')!.innerHTML = `<i data-lucide="link-2" class="w-3 h-3 text-gray-400"></i> ${agent.ad_url}`;

    let skillsHtml = '';
    agent.capabilities.forEach((cap: string) => {
        skillsHtml += `<span class="text-[11px] px-2 py-0.5 rounded-md bg-gray-50 text-gray-500 border border-gray-100 font-mono">${cap}</span>`;
    });
    document.getElementById('node-header-skills')!.innerHTML = skillsHtml;

    // Update online status badge
    const statusBadge = document.getElementById('node-header-status-badge');
    if (statusBadge) {
        const isOnline = agent.online === true;
        if (isOnline) {
            statusBadge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 flex items-center gap-1.5';
            statusBadge.innerHTML = '<span class="w-1 h-1 rounded-full bg-emerald-500"></span> Online';
        } else {
            statusBadge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100 flex items-center gap-1.5';
            statusBadge.innerHTML = '<span class="w-1 h-1 rounded-full bg-amber-500"></span> Offline';
        }
    }
    
    if (window.lucide) window.lucide.createIcons();
    (window as any).switchPage('view-node-sec', btnId);
};

// Auto fetch nodes on load
setTimeout(() => {
    if ((window as any).renderDynamicNodes) (window as any).renderDynamicNodes();
}, 500);

// ============================================================================
// Settings - ANP Config Management
// ============================================================================

function _showSettingsToast(message: string, isSuccess: boolean) {
    const toast = document.getElementById('settings-toast');
    const inner = document.getElementById('settings-toast-inner') as HTMLElement;
    const icon = document.getElementById('settings-toast-icon') as HTMLElement;
    const text = document.getElementById('settings-toast-text') as HTMLElement;
    if (!toast || !inner || !icon || !text) return;

    text.innerText = message;
    if (isSuccess) {
        inner.className = 'flex items-center gap-2.5 px-4 py-3 rounded-xl border shadow-lg text-sm bg-emerald-50 border-emerald-100 text-emerald-700';
        icon.setAttribute('data-lucide', 'check-circle');
    } else {
        inner.className = 'flex items-center gap-2.5 px-4 py-3 rounded-xl border shadow-lg text-sm bg-red-50 border-red-100 text-red-700';
        icon.setAttribute('data-lucide', 'x-circle');
    }
    if (window.lucide) window.lucide.createIcons();

    toast.classList.remove('opacity-0', 'translate-x-10', 'pointer-events-none');
    toast.classList.add('opacity-100', 'translate-x-0');
    setTimeout(() => {
        toast.classList.remove('opacity-100', 'translate-x-0');
        toast.classList.add('opacity-0', 'translate-x-10', 'pointer-events-none');
    }, 3000);
}

function _renderNodeAds(ads: string[]) {
    const container = document.getElementById('cfg-node-ads-list');
    if (!container) return;
    container.innerHTML = '';
    ads.forEach((url: string, index: number) => {
        container.insertAdjacentHTML('beforeend', `
            <div class="flex items-center gap-2 node-ad-item" data-index="${index}">
                <input type="text" value="${url.replace(/"/g, '"')}" placeholder="http://host:port/agent/ad.json"
                    class="node-ad-input flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                <button onclick="window.removeNodeAd(${index})" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                </button>
            </div>
        `);
    });
    if (window.lucide) window.lucide.createIcons();
}

(window as any).addNodeAd = function() {
    const container = document.getElementById('cfg-node-ads-list');
    if (!container) return;
    const count = container.querySelectorAll('.node-ad-item').length;
    container.insertAdjacentHTML('beforeend', `
        <div class="flex items-center gap-2 node-ad-item" data-index="${count}">
            <input type="text" value="" placeholder="http://host:port/agent/ad.json"
                class="node-ad-input flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
            <button onclick="window.removeNodeAd(${count})" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
            </button>
        </div>
    `);
    if (window.lucide) window.lucide.createIcons();
    // Focus the new input
    const inputs = container.querySelectorAll('.node-ad-input');
    if (inputs.length > 0) (inputs[inputs.length - 1] as HTMLInputElement).focus();
};

(window as any).removeNodeAd = function(index: number) {
    const container = document.getElementById('cfg-node-ads-list');
    if (!container) return;
    const items = container.querySelectorAll('.node-ad-item');
    if (items[index]) {
        (items[index] as HTMLElement).style.opacity = '0';
        (items[index] as HTMLElement).style.transform = 'scale(0.95)';
        setTimeout(() => {
            items[index].remove();
            // Re-index
            container.querySelectorAll('.node-ad-item').forEach((item, i) => {
                item.setAttribute('data-index', String(i));
                const btn = item.querySelector('button');
                if (btn) btn.setAttribute('onclick', `window.removeNodeAd(${i})`);
            });
        }, 150);
    }
};

function _collectNodeAds(): string[] {
    const container = document.getElementById('cfg-node-ads-list');
    if (!container) return [];
    const ads: string[] = [];
    container.querySelectorAll('.node-ad-input').forEach((input) => {
        const val = (input as HTMLInputElement).value.trim();
        if (val) ads.push(val);
    });
    return ads;
}

(window as any).loadSettingsConfig = async function() {
    const loading = document.getElementById('settings-loading');
    const disabled = document.getElementById('settings-disabled');
    const formContainer = document.getElementById('settings-form-container');
    const badge = document.getElementById('settings-anp-badge');
    if (!loading || !disabled || !formContainer || !badge) return;

    loading.classList.remove('hidden');
    disabled.classList.add('hidden');
    formContainer.classList.add('hidden');

    try {
        const res = await fetch('http://localhost:8001/api/config');
        const data = await res.json();

        if (data.error || !data.config) {
            loading.classList.add('hidden');
            disabled.classList.remove('hidden');
            badge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100';
            badge.innerText = 'Disabled';
            if (window.lucide) window.lucide.createIcons();
            return;
        }

        const cfg = data.config;

        // Fill form
        const el = (id: string) => document.getElementById(id) as HTMLInputElement | null;
        if (el('cfg-did')) el('cfg-did')!.value = cfg.did || '';
        if (el('cfg-did-doc-path')) el('cfg-did-doc-path')!.value = cfg.anpClient?.didDocPath || '';
        if (el('cfg-did-key-path')) el('cfg-did-key-path')!.value = cfg.anpClient?.didKeyPath || '';
        if (el('cfg-server-name')) el('cfg-server-name')!.value = cfg.anpServer?.name || '';
        if (el('cfg-server-prefix')) el('cfg-server-prefix')!.value = cfg.anpServer?.prefix || '';
        if (el('cfg-server-desc')) el('cfg-server-desc')!.value = cfg.anpServer?.description || '';
        if (el('cfg-server-port')) el('cfg-server-port')!.value = String(cfg.anpServer?.serverPort || '');
        if (el('cfg-server-private-key')) el('cfg-server-private-key')!.value = cfg.anpServer?.privateKeyPath || '';
        if (el('cfg-server-public-key')) el('cfg-server-public-key')!.value = cfg.anpServer?.publicKeyPath || '';

        _renderNodeAds(cfg.anpClient?.nodeAds || []);

        loading.classList.add('hidden');
        formContainer.classList.remove('hidden');
        badge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100';
        badge.innerText = 'Active';
        if (window.lucide) window.lucide.createIcons();
    } catch (e) {
        loading.classList.add('hidden');
        disabled.classList.remove('hidden');
        badge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-red-500 bg-red-50 border border-red-100';
        badge.innerText = 'Error';
        if (window.lucide) window.lucide.createIcons();
    }
};

(window as any).reloadSettingsConfig = function() {
    (window as any).loadSettingsConfig();
};

(window as any).saveSettingsConfig = async function() {
    const btn = document.getElementById('settings-save-btn') as HTMLButtonElement;
    if (!btn) return;

    const el = (id: string) => document.getElementById(id) as HTMLInputElement | null;
    const nodeAds = _collectNodeAds();

    const payload: any = {
        did: el('cfg-did')?.value || '',
        anpClient: {
            didDocPath: el('cfg-did-doc-path')?.value || '',
            didKeyPath: el('cfg-did-key-path')?.value || '',
            nodeAds: nodeAds,
        },
        anpServer: {
            name: el('cfg-server-name')?.value || '',
            prefix: el('cfg-server-prefix')?.value || '',
            description: el('cfg-server-desc')?.value || '',
            serverPort: parseInt(el('cfg-server-port')?.value || '8000', 10),
            privateKeyPath: el('cfg-server-private-key')?.value || '',
            publicKeyPath: el('cfg-server-public-key')?.value || '',
        },
    };

    // Show saving state
    btn.disabled = true;
    btn.classList.add('opacity-70');
    const origHtml = btn.innerHTML;
    btn.innerHTML = '<span class="flex items-center gap-1.5"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Saving...</span>';
    if (window.lucide) window.lucide.createIcons();

    try {
        const res = await fetch('http://localhost:8001/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.success) {
            _showSettingsToast('Configuration saved successfully', true);
            // Refresh form with server-validated values
            (window as any).loadSettingsConfig();
        } else {
            _showSettingsToast(data.error || 'Failed to save configuration', false);
        }
    } catch (e) {
        _showSettingsToast('Network error: failed to save', false);
    } finally {
        btn.disabled = false;
        btn.classList.remove('opacity-70');
        btn.innerHTML = origHtml;
        if (window.lucide) window.lucide.createIcons();
    }
};

