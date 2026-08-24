import 'element-plus/dist/index.css'
import './styles/main.css'

import ElementPlus from 'element-plus'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'

createApp(App).use(pinia).use(router).use(ElementPlus).mount('#app')
