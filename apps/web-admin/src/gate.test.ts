import { describe, expect, it } from 'vitest'
import { GATE_MIN_USERS, GATE_RATE, GATE_TEXT, gateVerdict } from './gate'

// 判定阈值真值表（docs/18 §6 T2）：rate≥0.8 且 n≥5，口径与
// apps/backend/forge_server/web_admin.py 的 GATE_RATE / GATE_MIN_USERS / reason 拼装同文。
// API 侧 rate = round(ok/first_runs, 4)（store.py stats_first_run），真值表按该口径取值。
describe('gateVerdict 判定真值表', () => {
  it('n=5 且 rate=0.8 —— 双边界同时压线 → 达标', () => {
    expect(gateVerdict({ first_runs: 5, rate: 0.8 })).toEqual({ met: true, reason: '' })
  })

  it('n=10 且 rate=0.9 —— 双双达标 → 达标', () => {
    expect(gateVerdict({ first_runs: 10, rate: 0.9 })).toEqual({ met: true, reason: '' })
  })

  it('n=4 且 rate=1.0 —— rate 达标但 n 不足 → 未达标，reason 报 n=4<5', () => {
    expect(gateVerdict({ first_runs: 4, rate: 1.0 })).toEqual({ met: false, reason: '（n=4<5）' })
  })

  it('n=10 且 rate=0.79 —— n 达标但 rate 不足 → 未达标，reason 为空（与 web_admin.py 同：rate 不足不附原因）', () => {
    expect(gateVerdict({ first_runs: 10, rate: 0.79 })).toEqual({ met: false, reason: '' })
  })

  it('n=0 且 rate=0 —— 空聚合 → 未达标，reason 报 n=0<5', () => {
    expect(gateVerdict({ first_runs: 0, rate: 0 })).toEqual({ met: false, reason: '（n=0<5）' })
  })

  it('n=7 且 rate=0.7999 —— rate 差一丝（API round 4 位口径）→ 未达标', () => {
    expect(gateVerdict({ first_runs: 7, rate: 0.7999 })).toEqual({ met: false, reason: '' })
  })
})

// 常量钉子：GATE_TEXT 必须与 backend web_admin.py GATE_TEXT 一字不差（卡面要求）。
describe('GATE 常量钉子（与 web_admin.py 同文）', () => {
  it('GATE_TEXT 与 web_admin.py 逐字符一致', () => {
    expect(GATE_TEXT).toBe(
      'MS-2 通过 = 每个上架应用首跑成功率 ≥80% 且 n≥5 不同真实注册用户；任一不达 → 不进 MS-3',
    )
  })

  it('GATE_RATE = 0.8，GATE_MIN_USERS = 5', () => {
    expect(GATE_RATE).toBe(0.8)
    expect(GATE_MIN_USERS).toBe(5)
  })
})
