<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const events = ref([])
const report = ref(null)
const bucket = ref(null)
const error = ref('')
const running = ref(false)

async function load() {
  events.value = await api.events()
  bucket.value = await api.channelBuckets()
}
async function run() {
  error.value = ''
  running.value = true
  try {
    // 失败整批回滚：后端抛错时不会有任何主桶增量 / 搁置 / 证明落库
    report.value = await api.ingest()
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    running.value = false
  }
}
onMounted(load)
</script>
<template>
  <div data-plant="24-channel-bucket-count-lie" class="plant-mark" style="display:none"></div>

  <div>
    <h1>装载</h1>
    <p class="sub">投柜 / 取件事件按 channel 入口分流；仅 primary 物化占用，secondary 入搁置，成功批固化通道分桶证明。</p>
    <p><button :disabled="running" @click="run">{{ running ? '装载中…' : '跑一批夹具' }}</button></p>
    <div v-if="error" class="panel" style="border-color: var(--over); color: var(--over); margin-top: 1rem">
      装载失败，整批已回滚：{{ error }}
    </div>
    <pre v-if="report" class="panel">{{ report }}</pre>

    <div v-if="bucket" class="panel" style="margin-top:1rem">
      <h2 style="margin-top:0">通道分桶证明
        <small v-if="!bucket.proven">（尚无成功批，空桶占位）</small>
      </h2>
      <div class="stats">
        <div class="stat"><b>{{ bucket.primary_n }}</b><span>primary_n（主通道）</span></div>
        <div class="stat"><b>{{ bucket.secondary_n }}</b><span>secondary_n（搁置）</span></div>
        <div class="stat"><b>{{ bucket.total_n ?? 0 }}</b><span>total_n</span></div>
        <div class="stat"><b>{{ (bucket.held_secondary_ids || []).length }}</b><span>held_secondary_ids</span></div>
      </div>
      <p class="sub" style="margin-bottom:0">
        批次 <code>{{ bucket.batch_id || '—' }}</code> ·
        secondary 不计入 primary accepted · 分桶与搁置互证
      </p>
      <pre v-if="bucket.held_secondary_ids && bucket.held_secondary_ids.length" class="panel" style="margin:.6rem 0 0">{{ bucket.held_secondary_ids }}</pre>
    </div>

    <div class="panel" style="margin-top:1rem; overflow:auto">
      <table>
        <thead><tr><th>事件</th><th>类型</th><th>格口</th><th>运单</th><th>时刻</th><th>通道</th></tr></thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td><code>{{ e.id }}</code></td>
            <td>{{ e.event_type }}</td>
            <td>{{ e.cell_id || '—' }}</td>
            <td>{{ e.tracking_no || '—' }}</td>
            <td>{{ e.event_ts }}</td>
            <td>{{ e.channel }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
