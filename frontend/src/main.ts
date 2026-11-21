import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startTelemetry } from './utils/telemetry'

import '@fortawesome/fontawesome-free/css/fontawesome.css'
import '@fortawesome/fontawesome-free/css/solid.css'
import '@fortawesome/fontawesome-free/css/brands.css'
import './assets/sass/main.scss'

// Telemetry is optional, so a failure to start it leaves the API's no-op tracer and logger, and the app still mounts.
try {
  startTelemetry()
} catch (error) {
  console.error('telemetry_start_failed', error)
}

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
