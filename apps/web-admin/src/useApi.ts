import { useCallback, useEffect, useState } from 'react'

/** 只读拉取状态机：loading → done | error；reload 重新进入 loading。
 * 组件卸载后的迟到响应直接丢弃（cancelled 标记），不产生 setState 竞态。 */
export type ApiState<T> =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'done'; data: T }

export function useApi<T>(loader: () => Promise<T>) {
  const [reloadKey, setReloadKey] = useState(0)
  const [state, setState] = useState<ApiState<T>>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ phase: 'loading' })
    loader().then(
      (data) => {
        if (!cancelled) setState({ phase: 'done', data })
      },
      (err: unknown) => {
        if (!cancelled) {
          setState({
            phase: 'error',
            message: err instanceof Error ? err.message : String(err),
          })
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [loader, reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])
  return { state, reload }
}
