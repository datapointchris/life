<template>
  <ul
    class="habit-checklist"
    data-testid="habit-checklist"
  >
    <li
      v-for="item in checklist.items"
      :key="item.id"
      class="habit-checklist__item"
      :class="{ 'habit-checklist__item--done': item.done }"
      data-testid="habit-checklist-item"
    >
      <span class="habit-checklist__name">{{ item.name }}</span>
      <span class="habit-checklist__boxes">
        <button
          v-for="n in Math.max(item.daily_target, item.ticks.length)"
          :key="n"
          type="button"
          class="habit-checklist__box"
          :class="{ 'habit-checklist__box--ticked': n <= item.ticks.length }"
          :aria-label="`${n <= item.ticks.length ? 'Untick' : 'Tick'} ${item.name} ${n} of ${item.daily_target}`"
          :aria-pressed="n <= item.ticks.length"
          :disabled="busy.has(item.id)"
          data-testid="habit-checklist-box"
          @click="press(item, n)"
        >
          <i
            v-if="n <= item.ticks.length"
            class="fa-solid fa-check"
          ></i>
        </button>
      </span>
    </li>
  </ul>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useHabitsStore } from '@/stores/habits'
import { useNotifications } from '@/composables/useNotifications'
import { ApiError } from '@/api/errors'
import type { HabitChecklist, HabitChecklistItemDay } from '@/api/client'

defineProps<{ checklist: HabitChecklist }>()

const store = useHabitsStore()
const { show: notify } = useNotifications()
const busy = ref(new Set<number>())

// A ticked box takes back the item's latest tick, whichever ticked box was
// pressed; an empty box adds one. So a mistaken tap is undone where it happened.
async function press(item: HabitChecklistItemDay, n: number) {
  if (busy.value.has(item.id)) return
  busy.value.add(item.id)
  const latest = item.ticks[item.ticks.length - 1]
  try {
    if (n <= item.ticks.length && latest) await store.untickItem(item.id, latest.id)
    else await store.tickItem(item.id)
  } catch (e) {
    const detail = e instanceof ApiError ? e.userMessage : String(e)
    notify(`Failed to update ${item.name}: ${detail}`, 'error')
  } finally {
    busy.value.delete(item.id)
  }
}
</script>
