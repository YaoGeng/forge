/** GATE 判定纯函数（docs/18 §6 T2）：判定式与 backend web_admin.py 钉死同文。 */
export const GATE_TEXT =
  'MS-2 通过 = 每个上架应用首跑成功率 ≥80% 且 n≥5 不同真实注册用户；任一不达 → 不进 MS-3'
export const GATE_RATE = 0.8
export const GATE_MIN_USERS = 5

export interface GateVerdict {
  met: boolean
  /** 未达标时的原因文案；仅 n 不足时给出（与 web_admin.py reason 拼装同文），rate 不足为空 */
  reason: string
}

export function gateVerdict(stat: { first_runs: number; rate: number }): GateVerdict {
  const { first_runs: n, rate } = stat
  const met = n >= GATE_MIN_USERS && rate >= GATE_RATE
  // 与 web_admin.py 同款：reason 仅在 n 不足时给出；rate 不足不附原因
  const reason = met ? '' : n < GATE_MIN_USERS ? `（n=${n}<${GATE_MIN_USERS}）` : ''
  return { met, reason }
}
