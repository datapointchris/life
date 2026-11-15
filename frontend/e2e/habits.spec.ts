import { test, expect } from '@playwright/test'

const SUCCESS = '.flash-messages__message--success'
const ERROR = '.flash-messages__message--error'

/** Helper: open the add category modal, fill in name, and submit */
async function createCategory(page: import('@playwright/test').Page, name: string) {
  await page.getByTestId('category-add-button').click()
  await expect(page.getByTestId('category-name-input')).toBeVisible({ timeout: 5000 })
  await page.getByTestId('category-name-input').fill(name)
  await page.getByTestId('category-name-input').press('Enter')
  await expect(page.locator(SUCCESS).first()).toBeVisible({ timeout: 5000 })
}

/** Helper: open the add habit modal, fill in name and category, and submit */
async function createHabit(page: import('@playwright/test').Page, name: string, categoryName: string) {
  await page.getByTestId('habit-add-button').click()
  await expect(page.getByTestId('habit-name-input')).toBeVisible({ timeout: 5000 })
  await page.getByTestId('habit-name-input').fill(name)
  await page.getByTestId('habit-category-input').click()
  await page.locator('.neu-select__option', { hasText: categoryName }).click()
  await page.getByTestId('habit-name-input').press('Enter')
  await expect(page.locator(SUCCESS).first()).toBeVisible({ timeout: 5000 })
  await expect(page.getByTestId('habit-name-input')).not.toBeVisible({ timeout: 5000 })
}

// Smoke tests only — interaction-heavy tests (edit, complete, hibernate,
// revive, filter) are covered by component integration tests in
// src/views/__tests__/HabitsViews.test.ts

test.describe('Habits Page', () => {
  test('API calls succeed through Traefik routing (CORS check)', async ({ page }) => {
    const apiErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error' && msg.text().includes('request_')) {
        apiErrors.push(msg.text())
      }
    })

    await page.goto('/habits')
    await expect(page).toHaveTitle('Daily Habits | Life')
    await expect(page.locator(ERROR)).not.toBeVisible()
    expect(apiErrors).toEqual([])
  })

  test('navigates to manage page', async ({ page }) => {
    await page.goto('/habits/manage')
    await expect(page.locator('h3', { hasText: 'Current Categories' })).toBeVisible({ timeout: 10000 })
  })

  test('navigates to completed page', async ({ page }) => {
    await page.goto('/habits/completed')
    await expect(page).toHaveTitle('Completed Habits | Life')
  })

  test('creates a category and habit, then gives the habit a checklist', async ({ page }) => {
    await page.goto('/habits/manage')
    await expect(page.locator('h3', { hasText: 'Current Categories' })).toBeVisible({ timeout: 10000 })

    const catName = `E2E Cat ${Date.now()}`
    await createCategory(page, catName)
    await expect(page.locator(SUCCESS).first()).toContainText('added')

    const habitName = `E2E Habit ${Date.now()}`
    await createHabit(page, habitName, catName)

    const row = page.getByTestId('habit-item').filter({ hasText: habitName })
    await expect(row).toBeVisible()

    await row.getByTestId('habit-edit-button').click()
    await page.getByTestId('habit-add-item-button').click()
    await page.getByTestId('habit-item-name-0').fill('Squat')
    await page.getByTestId('habit-item-target-0').fill('2')
    await page.getByTestId('habit-submit-button').click()
    await expect(page.locator(SUCCESS).filter({ hasText: 'updated' })).toBeVisible({ timeout: 5000 })

    await page.goto('/habits')
    const checklist = page.locator('.habits__item', { hasText: habitName }).getByTestId('habit-checklist-item')
    await expect(checklist).toContainText('Squat')
    await expect(checklist.getByTestId('habit-checklist-box')).toHaveCount(2)
  })

  test('subnav navigation between sub-pages works', async ({ page }) => {
    await page.goto('/habits')
    await expect(page).toHaveURL(/\/habits$/)

    await page.getByTestId('habits-subnav-completed').click()
    await expect(page).toHaveURL(/\/habits\/completed/)

    await page.getByTestId('habits-subnav-manage').click()
    await expect(page).toHaveURL(/\/habits\/manage/)

    await page.getByTestId('habits-subnav-daily').click()
    await expect(page).toHaveURL(/\/habits$/)
  })

  test('sidebar navigation to habits works', async ({ page }) => {
    await page.goto('/habits')
    await expect(page).toHaveTitle('Daily Habits | Life')

    const sidebarLink = page.locator('.nav-link--active', { hasText: 'Habits' })
    await expect(sidebarLink).toBeVisible()
  })
})
