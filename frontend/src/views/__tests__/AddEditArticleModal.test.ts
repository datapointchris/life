import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import AddEditArticleModal from '@/components/articles/AddEditArticleModal.vue'

vi.mock('@/composables/useNotifications', () => ({
  useNotifications: () => ({ show: vi.fn(), close: vi.fn(), closeAll: vi.fn(), notifications: { value: [] } }),
}))

describe('AddEditArticleModal', () => {
  it('saves an edit to an article that has no summary', async () => {
    const editData = { id: 4, title: 'Saved by a link', url: 'https://example.com/a', tags: [], summary: null }
    const wrapper = mount(AddEditArticleModal, {
      props: { visible: false, editData },
      global: {
        plugins: [createTestingPinia({ stubActions: true, createSpy: vi.fn })],
        stubs: {
          AddEditModal: {
            template: '<div><slot :handle-close="() => {}" :handle-success="() => {}" /></div>',
            props: ['visible', 'focusRef'],
          },
        },
      },
    })
    await wrapper.setProps({ visible: true })

    await wrapper.get('[data-testid="article-title-input"]').setValue('Renamed')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('update')).toEqual([[4, { title: 'Renamed', tags: [], summary: null, notes: undefined }]])
  })
})
