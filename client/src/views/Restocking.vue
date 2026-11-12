<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <label class="budget-label" for="restock-budget">{{ t('restocking.budget') }}</label>
        <div class="budget-value">{{ money(budget) }}</div>
        <input
          id="restock-budget"
          class="budget-slider"
          type="range"
          min="0"
          :max="sliderMax"
          step="1000"
          :value="budget"
          :aria-label="t('restocking.budget')"
          @input="onBudgetInput"
        />
        <div class="budget-range">
          <span>{{ money(0) }}</span>
          <span>{{ money(sliderMax) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ money(budget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ money(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ money(remaining) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.itemsToRestock') }}</div>
          <div class="stat-value">{{ items.length }}</div>
        </div>
      </div>

      <div v-if="orderSuccess" class="success-banner" role="status">
        <span>
          {{ t('restocking.orderPlaced', { number: orderSuccess.number, date: orderSuccess.date }) }}
          <router-link to="/orders" class="banner-link">{{ t('restocking.viewOrders') }}</router-link>
        </span>
        <button type="button" class="banner-dismiss" aria-label="Dismiss" @click="orderSuccess = null">&times;</button>
      </div>
      <div v-if="orderError" class="error-banner" role="alert">{{ orderError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="items.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="items.length === 0">
                <td colspan="8" class="empty-row">{{ t('restocking.noRecommendations') }}</td>
              </tr>
              <tr v-for="item in items" :key="item.sku">
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ item.name }}</td>
                <td>{{ categoryLabel(item.category) }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ trendLabel(item.trend) }}</span>
                </td>
                <td>{{ item.quantity }}</td>
                <td>{{ money(item.unit_cost, 2) }}</td>
                <td><strong>{{ money(item.line_total) }}</strong></td>
                <td>{{ t('orders.leadTimeDays', { days: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const DEBOUNCE_MS = 250
const CATEGORY_KEYS = {
  'Circuit Boards': 'circuitBoards',
  'Sensors': 'sensors',
  'Actuators': 'actuators',
  'Controllers': 'controllers',
  'Power Supplies': 'powerSupplies'
}

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const sliderMax = ref(0)
    const budget = ref(0)
    const items = ref([])
    const totalCost = ref(0)
    const remaining = ref(0)

    const submitting = ref(false)
    const orderSuccess = ref(null)
    const orderError = ref(null)

    let debounceTimer = null
    // Incremented per request so a slow earlier response can't overwrite a newer one
    let requestCounter = 0

    const money = (amount, decimals = 0) => {
      return decimals > 0
        ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
        : formatCurrency(amount, currentCurrency.value)
    }

    const categoryLabel = (category) => {
      const key = CATEGORY_KEYS[category]
      return key ? t(`categories.${key}`) : category
    }

    const trendLabel = (trend) => {
      const key = `trends.${trend}`
      const label = t(key)
      // t() may echo the key when missing; fall back to the raw value
      return label === key ? trend : label
    }

    const formatDate = (dateString) => {
      // Date-only strings parse as UTC; build a local date to avoid a one-day shift
      const [y, m, d] = String(dateString).split('-').map(Number)
      const date = new Date(y, m - 1, d)
      if (isNaN(date.getTime())) return dateString
      return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    const loadRecommendations = async (value) => {
      const requestId = ++requestCounter
      try {
        const data = await api.getRestockRecommendations(value)
        if (requestId !== requestCounter) return // stale response
        items.value = data.items
        totalCost.value = data.total_cost
        remaining.value = data.remaining_budget
        error.value = null
      } catch (err) {
        if (requestId !== requestCounter) return
        error.value = 'Failed to load recommendations: ' + err.message
      }
    }

    const onBudgetInput = (event) => {
      budget.value = Number(event.target.value)
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => loadRecommendations(budget.value), DEBOUNCE_MS)
    }

    const placeOrder = async () => {
      if (items.value.length === 0 || submitting.value) return
      submitting.value = true
      orderError.value = null
      orderSuccess.value = null
      try {
        const order = await api.createRestockOrder(
          items.value.map(item => ({ sku: item.sku, quantity: item.quantity }))
        )
        orderSuccess.value = {
          number: order.order_number,
          date: formatDate(order.expected_delivery)
        }
      } catch (err) {
        orderError.value = err.response?.data?.detail || t('restocking.orderFailed')
      } finally {
        submitting.value = false
      }
    }

    onMounted(async () => {
      try {
        // Budget 0 call is only used to learn the maximum useful budget
        const initial = await api.getRestockRecommendations(0)
        sliderMax.value = Math.ceil(initial.max_budget / 1000) * 1000
        budget.value = sliderMax.value
        await loadRecommendations(budget.value)
      } catch (err) {
        error.value = 'Failed to load recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    })

    onUnmounted(() => {
      clearTimeout(debounceTimer)
    })

    return {
      t,
      loading,
      error,
      sliderMax,
      budget,
      items,
      totalCost,
      remaining,
      submitting,
      orderSuccess,
      orderError,
      money,
      categoryLabel,
      trendLabel,
      onBudgetInput,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  color: #64748b;
}

.budget-value {
  font-size: 2rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0.25rem 0 1rem;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  border: none;
  cursor: pointer;
}

.budget-slider::-moz-range-track {
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  border: none;
  cursor: pointer;
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.4);
}

.budget-slider:focus-visible::-moz-range-thumb {
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.4);
}

.budget-range {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

.place-order-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.place-order-btn:hover:not(:disabled) {
  background: #2563eb;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  color: #f8fafc;
  cursor: not-allowed;
}

.success-banner,
.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-bottom: 1.5rem;
  font-size: 0.875rem;
}

.success-banner {
  background: #dcfce7;
  border: 1px solid #86efac;
  color: #166534;
}

.error-banner {
  background: #fee2e2;
  border: 1px solid #fca5a5;
  color: #991b1b;
}

.banner-link {
  margin-left: 0.5rem;
  font-weight: 600;
  color: inherit;
  text-decoration: underline;
}

.banner-dismiss {
  background: none;
  border: none;
  color: inherit;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
}

.empty-row {
  text-align: center;
  color: #64748b;
}

.table-container {
  overflow-x: auto;
}
</style>
