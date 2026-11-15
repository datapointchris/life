<template>
  <AddEditModal
    :visible="visible"
    :focus-ref="nameInput"
    @close="handleModalClose"
  >
    <template #default="{ handleClose, handleSuccess }">
      <form
        class="add-edit-modal__form"
        @submit.prevent="handleSubmit(handleSuccess)"
      >
        <h2>{{ editData ? 'Edit Habit' : 'Add Habit' }}</h2>

        <div class="add-edit-modal__form-item">
          <label for="habit-name">Name</label>
          <input
            id="habit-name"
            ref="nameInput"
            v-model="form.name"
            data-testid="habit-name-input"
            type="text"
            class="textbox"
            required
          />
        </div>

        <div class="add-edit-modal__form-item">
          <label for="habit-category">Category</label>
          <NeuSelect
            :model-value="form.category_id"
            :options="categoryOptions"
            data-testid="habit-category-input"
            placeholder="Select a category"
            @update:model-value="form.category_id = $event"
          />
        </div>

        <div class="add-edit-modal__form-item">
          <div class="habit-checklist-editor__header">
            <label>Checklist</label>
            <button
              type="button"
              class="button button--small"
              data-testid="habit-add-item-button"
              @click="addItem"
            >
              <span class="button__text">+ Add Item</span>
            </button>
          </div>
          <div
            v-for="(item, idx) in form.items"
            :key="item.key"
            class="habit-checklist-editor__row"
            data-testid="habit-item-row"
          >
            <input
              v-model="item.name"
              type="text"
              class="textbox"
              placeholder="Item, e.g. Push-up"
              :aria-label="`Item ${idx + 1} name`"
              required
              :data-testid="`habit-item-name-${idx}`"
            />
            <input
              v-model.number="item.daily_target"
              type="number"
              min="1"
              step="1"
              class="textbox habit-checklist-editor__target"
              :aria-label="`Item ${idx + 1} times a day`"
              title="Times a day"
              required
              :data-testid="`habit-item-target-${idx}`"
            />
            <ActionButton
              type="button"
              icon="fa-regular fa-trash-can"
              variant="danger"
              :title="`Remove ${item.name || 'item'}`"
              :data-testid="`habit-item-remove-${idx}`"
              @click="removeItem(idx)"
            />
          </div>
          <p
            v-if="form.items.length === 0"
            class="habit-checklist-editor__empty"
          >
            No checklist. The habit is done when you check it off.
          </p>
        </div>

        <div class="add-edit-modal__form-buttons">
          <button
            type="submit"
            data-testid="habit-submit-button"
            class="button"
          >
            <span class="button__text">{{ editData ? 'Update' : 'Add' }} Habit</span>
          </button>
          <button
            type="button"
            data-testid="habit-cancel-button"
            class="button button--danger"
            @click="handleClose()"
          >
            <span class="button__text button__text--danger">Cancel</span>
          </button>
        </div>
      </form>
    </template>
  </AddEditModal>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch } from 'vue'
import type { HabitCreate, HabitUpdate, HabitCategory, HabitChecklistItem } from '@/api/client'
import type { ChecklistItemDraft } from '@/stores/habits'
import ActionButton from '@/components/ActionButton.vue'
import AddEditModal from '@/components/AddEditModal.vue'
import NeuSelect from '@/components/NeuSelect.vue'

const props = defineProps<{
  visible: boolean
  categories: HabitCategory[]
  editData?: {
    id: number
    name: string
    category_id: number
    items: HabitChecklistItem[]
  } | null
}>()

const emit = defineEmits<{
  close: []
  create: [data: HabitCreate, checklist: ChecklistItemDraft[]]
  update: [id: number, data: HabitUpdate, checklist: ChecklistItemDraft[]]
}>()

const nameInput = ref<HTMLInputElement | null>(null)

const categoryOptions = computed(() => props.categories.map((cat) => ({ value: cat.id, label: cat.name })))

// `key` keeps each row's inputs attached to it while rows above are removed.
type ItemRow = ChecklistItemDraft & { key: number }
let nextKey = 0

const form = reactive({
  name: '',
  category_id: null as number | null,
  items: [] as ItemRow[],
})

watch(
  () => props.visible,
  (val) => {
    if (val && props.editData) {
      form.name = props.editData.name
      form.category_id = props.editData.category_id
      form.items = props.editData.items.map((i) => ({ id: i.id, name: i.name, daily_target: i.daily_target, key: nextKey++ }))
    }
  }
)

function addItem() {
  form.items.push({ id: null, name: '', daily_target: 1, key: nextKey++ })
}

function removeItem(idx: number) {
  form.items.splice(idx, 1)
}

function resetForm() {
  form.name = ''
  form.category_id = null
  form.items = []
}

function handleModalClose() {
  resetForm()
  emit('close')
}

function handleSubmit(handleSuccess: () => void) {
  if (!form.name.trim() || !form.category_id) return
  const checklist = form.items.map((i) => ({ id: i.id, name: i.name.trim(), daily_target: Number(i.daily_target) }))
  if (checklist.some((i) => !i.name || !Number.isInteger(i.daily_target) || i.daily_target < 1)) return
  const fields = { name: form.name.trim(), category_id: Number(form.category_id) }
  if (props.editData) {
    emit('update', props.editData.id, fields, checklist)
  } else {
    emit('create', fields, checklist)
  }
  handleSuccess()
}
</script>
