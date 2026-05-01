import { createContext } from 'react'

export const AppContext = createContext({
  tagMap: {},       // { tag: { tag, display_name, description } }
  openPlayer: () => {},
  player: null,
})
