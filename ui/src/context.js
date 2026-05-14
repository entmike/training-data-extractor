import { createContext } from 'react'

export const AppContext = createContext({
  tagMap: {},
  openPlayer: () => {},
  refreshTags: () => {},
  nsfwEnabled: false,
  setNsfwEnabled: () => {},
  configOpen: false,
  toggleConfig: () => {},
  queueOpen: false,
  toggleQueue: () => {},
  // ComfyUI queue (polled at app level)
  comfyQueue: null,      // { running, pending } | null
  comfyHistory: null,    // { history } | null
  comfyProgress: null,   // { value, max, prompt_id, node, node_value } | null
  comfyError: null,
  fetchComfyQueue: () => {},
  deleteQueueItem: async () => {},
  clearComfyQueue: async () => {},
})
