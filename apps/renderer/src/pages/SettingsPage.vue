<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ArrowLeft, Search, UserRound, Bot, Palette, Box, Info, ChartNoAxesCombined, CircleHelp } from 'lucide-vue-next';
import { settingsServices } from '../features/pageServices';
import type { SettingsSection } from '../features/pageServices';
import AccountPage from './AccountPage.vue';
import HelpPage from './HelpPage.vue';
const { current, tabs, select, close, ready } = settingsServices.use();
const query = ref('');
const matches = computed(() => tabs.filter(tab => tab.label.toLowerCase().includes(query.value.trim().toLowerCase())));
const icons = { account: UserRound, text: Bot, routing: ChartNoAxesCombined, appearance: Palette, components: Box, about: Info, help: CircleHelp };
const title = computed(() => tabs.find(tab => tab.key === current.value)?.label || '设置');
const groups: { title: string; keys: SettingsSection[] }[] = [
  { title: '个人', keys: ['account', 'appearance'] },
  { title: '工作区', keys: ['text', 'routing', 'components'] },
  { title: '产品', keys: ['about', 'help'] },
];
onMounted(() => ready(true));
onUnmounted(() => ready(false));
</script>

<template>
  <div class="settings-page">
    <aside class="settings-navigation" aria-label="设置导航">
      <div class="settings-navigation-heading"><h1>设置</h1><button class="settings-back" type="button" aria-label="返回工作区" title="返回工作区" @click="close"><ArrowLeft :size="17" /></button></div>
      <label class="settings-search"><Search :size="15" /><input v-model="query" type="search" placeholder="搜索设置" aria-label="搜索设置" /></label>
      <nav aria-label="设置分类">
        <template v-for="group in groups" :key="group.title">
          <div v-if="matches.some(tab => group.keys.includes(tab.key))" class="settings-nav-group">
            <p>{{ group.title }}</p>
            <button v-for="tab in matches.filter(tab => group.keys.includes(tab.key))" :key="tab.key" type="button" :class="{ active: current === tab.key }" :aria-current="current === tab.key ? 'page' : undefined" @click="select(tab.key)"><component :is="icons[tab.key]" :size="16" /><span>{{ tab.label }}</span></button>
          </div>
        </template>
        <p v-if="!matches.length" class="settings-no-results">没有匹配的设置</p>
      </nav>
    </aside>
    <section class="settings-main" :aria-label="title">
      <div class="settings-content">
        <header v-if="current !== 'account'" class="settings-page-heading"><h2>{{ title }}</h2></header>
        <AccountPage v-if="current === 'account'" />
        <HelpPage v-else-if="current === 'help'" />
        <div id="settings-content-host" />
      </div>
    </section>
  </div>
</template>
