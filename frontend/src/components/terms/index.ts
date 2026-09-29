/**
 * 术语词典合并入口（全平台唯一查词口）
 * ====================================
 * 词条分两处存放，按领域切：
 *   - `glossary.ts`  —— 平台通用 + 回测（标的、策略、夏普、最大回撤……）
 *   - `optimize.ts`  —— 组合优化专属（协方差、有效前沿、风险贡献……）
 *
 * **用词一律走本文件的 `term()`**，不要直接 import 上面两个文件 ——
 * 直接 import 会漏掉另一个领域的词条，症状是「有的词有解释、有的词直接抛错」。
 *
 * ⚠️ 合并时**显式检测重名并抛错**。
 *    用 `{...A, ...B}` 裸合并的话，后写的那个会**静默覆盖**先写的解释 ——
 *    界面上不报任何错，只是某个词的解释悄悄换了内容（甚至换成了另一个领域的说法）。
 *    这类问题构建、typecheck、渲染都拦不住，所以在这里让它直接炸。
 */
import { GLOSSARY as BASE_GLOSSARY, type Term } from './glossary'
import { OPTIMIZE_GLOSSARY } from './optimize'

export type { Term } from './glossary'

function mergeGlossaries(
  sources: Record<string, Record<string, Term>>,
): Record<string, Term> {
  const out: Record<string, Term> = {}
  for (const [name, dict] of Object.entries(sources)) {
    for (const [key, term] of Object.entries(dict)) {
      if (out[key]) {
        throw new Error(
          `术语词典重名：'${key}' 在多个领域文件里都定义了（后者来自 ${name}）。` +
            `重名会静默覆盖已有的解释，请改名或删掉其中一个。`,
        )
      }
      out[key] = term
    }
  }
  return out
}

/** 合并后的全量词典。 */
export const GLOSSARY: Record<string, Term> = mergeGlossaries({
  glossary: BASE_GLOSSARY,
  optimize: OPTIMIZE_GLOSSARY,
})

/** 查词条；不存在时**不静默吞掉** —— 写错 id 应该立刻炸，而不是界面上少一个解释却无人发现。 */
export function term(id: string): Term {
  const t = GLOSSARY[id]
  if (!t) throw new Error(`术语词典缺少词条：${id}`)
  return t
}
