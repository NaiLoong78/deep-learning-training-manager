<script setup lang="ts">
import type { ParameterDefinition } from '../types'

defineProps<{
  parameters: ParameterDefinition[]
  modelValue: Record<string, unknown>
  disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()

function update(current: Record<string, unknown>, key: string, value: unknown) {
  emit('update:modelValue', { ...current, [key]: value })
}
</script>

<template>
  <div v-if="parameters.length" class="parameter-grid">
    <div v-for="parameter in parameters" :key="parameter.key" class="parameter-item" :class="{ readonly: parameter.read_only }">
      <div class="parameter-head">
        <label>{{ parameter.label }}</label>
        <span v-if="parameter.runtime_editable" class="runtime-badge">运行时可调</span>
      </div>
      <el-select
        v-if="parameter.choices?.length"
        :model-value="modelValue[parameter.key]"
        :disabled="disabled || parameter.read_only"
        @update:model-value="update(modelValue, parameter.key, $event)"
      >
        <el-option v-for="choice in parameter.choices" :key="String(choice)" :label="String(choice)" :value="choice" />
      </el-select>
      <el-switch
        v-else-if="parameter.type === 'boolean'"
        :model-value="Boolean(modelValue[parameter.key])"
        :disabled="disabled || parameter.read_only"
        @update:model-value="update(modelValue, parameter.key, $event)"
      />
      <el-input-number
        v-else-if="parameter.type === 'integer' || parameter.type === 'number'"
        :model-value="Number(modelValue[parameter.key] ?? 0)"
        :min="parameter.minimum"
        :max="parameter.maximum"
        :step="parameter.type === 'integer' ? 1 : Math.max(Number(modelValue[parameter.key] || 0.001) / 10, 0.000001)"
        :precision="parameter.type === 'integer' ? 0 : undefined"
        :disabled="disabled || parameter.read_only"
        controls-position="right"
        @update:model-value="update(modelValue, parameter.key, $event)"
      />
      <el-input
        v-else
        :model-value="String(modelValue[parameter.key] ?? '')"
        :disabled="disabled || parameter.read_only"
        @update:model-value="update(modelValue, parameter.key, $event)"
      />
      <p>{{ parameter.help }}</p>
      <code>{{ parameter.key }}<template v-if="parameter.flag"> · {{ parameter.flag }}</template></code>
    </div>
  </div>
  <el-empty v-else description="未发现可调参数，将使用项目默认配置运行" :image-size="72" />
</template>

