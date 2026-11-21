<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
const proofs = ref([])
const bucketProofs = ref([])
const verification = ref(null)

async function load() {
  proofs.value = await api.proofs()
  bucketProofs.value = await api.channelBucketProofs()
  verification.value = await api.channelBucketVerify()
}
onMounted(load)
</script>
<template>
  <div data-plant="24-channel-bucket-count-lie" class="plant-mark" style="display:none"></div>

  <div>
    <h1>核账</h1>
    <p class="sub">占用核对列表与通道分桶核证；分桶证明 × 搁置集合 × 正式事件表 × 批回执全量对撞。</p>

    <div v-if="verification" class="panel" :style="{ borderColor: verification.ok ? 'var(--free)' : 'var(--over)' }">
      <h2 style="margin-top:0">通道分桶核证
        <span :style="{ color: verification.ok ? 'var(--free)' : 'var(--over)' }">
          {{ verification.ok ? '全部互证通过' : '存在分叉' }}
        </span>
      </h2>
      <div class="stats">
        <div class="stat"><b>{{ verification.proof_total }}</b><span>分桶证明批数</span></div>
        <div class="stat"><b>{{ verification.batch_total }}</b><span>装载批数</span></div>
        <div class="stat"><b>{{ verification.non_primary_events }}</b><span>正式表非 primary</span></div>
        <div class="stat"><b>{{ verification.held_leak_event_ids.length }}</b><span>搁置泄漏事件</span></div>
      </div>
      <ul style="margin-bottom:0">
        <li v-for="(v, k) in verification.checks" :key="k" :style="{ color: v ? 'var(--free)' : 'var(--over)' }">
          <code>{{ k }}</code>：{{ v ? 'PASS' : 'FAIL' }}
        </li>
      </ul>
      <div v-for="item in verification.per_batch" :key="item.batch_id">
        <p v-if="item.problems.length" style="color: var(--over); margin-bottom:0">
          <code>{{ item.batch_id }}</code>：{{ item.problems.join('；') }}
        </p>
      </div>
    </div>

    <div class="panel" style="margin-top:1rem; overflow:auto">
      <h2 style="margin-top:0">通道分桶证明（不可变快照）</h2>
      <table>
        <thead>
          <tr><th>批次</th><th>primary_n</th><th>secondary_n</th><th>total_n</th><th>held_secondary_ids</th><th>固化时刻</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in bucketProofs" :key="p.batch_id">
            <td><code>{{ p.batch_id }}</code></td>
            <td>{{ p.primary_n }}</td>
            <td>{{ p.secondary_n }}</td>
            <td>{{ p.total_n }}</td>
            <td><code>{{ p.held_secondary_ids.join(', ') || '—' }}</code></td>
            <td>{{ p.created_at }}</td>
          </tr>
          <tr v-if="!bucketProofs.length"><td colspan="6">尚无成功装载批</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel" style="margin-top:1rem; overflow:auto">
      <h2 style="margin-top:0">占用证明</h2>
      <table>
        <thead><tr><th>占用</th><th>格口</th><th>运单</th><th>开启</th><th>事件</th></tr></thead>
        <tbody>
          <tr v-for="p in proofs" :key="p.id">
            <td><code>{{ p.occupancy_id }}</code></td>
            <td>{{ p.cell_id }}</td>
            <td>{{ p.tracking_no }}</td>
            <td>{{ p.opened_at }}</td>
            <td><code>{{ p.event_ids_json }}</code></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
