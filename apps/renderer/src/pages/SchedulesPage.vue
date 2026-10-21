<script setup lang="ts">
import SchedulePanel from '../components/SchedulePanel.vue';
import { scheduleServices } from '../features/pageServices';
const { options, openProject, openSettings, changed } = scheduleServices.use();
</script>

<template>
<SchedulePanel v-bind="options" @open-project="openProject" @open-settings="openSettings" @changed="changed" />
</template>
