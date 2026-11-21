import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { startTelemetry } from './utils/telemetry'

import '@fortawesome/fontawesome-free/css/fontawesome.css'
import '@fortawesome/fontawesome-free/css/solid.css'
import '@fortawesome/fontawesome-free/css/brands.css'
import './assets/sass/main.scss'

startTelemetry()

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
