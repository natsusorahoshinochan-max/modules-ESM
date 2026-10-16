import { RegionEditor } from '../../residue_data/components/RegionEditor'
import type { ModuleViewerProps } from '../../../webui/src/module-ui'

function AlignmentRegions({ reading }: ModuleViewerProps) {
  const value = reading.value as Record<string, unknown>
  const subject = value.subject as { candidate_id: string }
  const reference = value.reference as { candidate_id: string }
  return <section aria-label="结构区域比较结果">
    <p>主体：{subject.candidate_id}；参考：{reference.candidate_id}</p>
    <p>主体区域：{(value.subject_region as string[] | undefined)?.join('、') || '未记录'}</p>
    <p>参考区域：{(value.reference_region as string[] | undefined)?.join('、') || '未记录'}</p>
    <p>RMSD：{String(value.rmsd)} Å；覆盖率：{String(value.coverage)}</p>
    <details><summary>自动对应、变换与计算来源</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
  </section>
}
type Statistic = { subject: { candidate_id: string }; source_metric: { contract_id: string }; source_method: { contract_id: string }; region: string[]; mean: number; valid_count: number; selected_count: number; missing_values: string }
function RegionalStatistics({ reading }: ModuleViewerProps) {
  const entries = (reading.value as { entries: Statistic[] }).entries
  return <section aria-label="区域统计结果"><p>原指标单位下的算术均值；每项保留原观测主体与来源，不重新预测。</p>{entries.map((entry, index) => <article key={index}>
    <h4>{entry.subject.candidate_id} · {entry.source_metric.contract_id}</h4>
    <p>区域：{entry.region.join('、')}</p><p>均值：{entry.mean}；有效数量：{entry.valid_count} / 所选数量：{entry.selected_count}</p>
    <p>缺值处理：{entry.missing_values === 'require_all' ? '所有位置必须有值' : '排除缺值'}；原方法：{entry.source_method.contract_id}</p>
    <details><summary>原始观测与统计来源</summary><pre>{JSON.stringify(entry, null, 2)}</pre></details>
  </article>)}</section>
}
export function register() { return { RegionEditor, AlignmentRegions, RegionalStatistics } }
