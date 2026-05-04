const API_URL = "https://api.openrouteservice.org/v2/directions/driving-car";
const API_KEY = "5b3ce3597851110001cf6248c8230188686a4e32906e872e42429472";

const TILES = {
    dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    light: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
};

let map, currentTileLayer;
let courierMarkers = {};
let courierPolylines = {};
let orderMarkers = {};
let orderPolylines = {};
let courierRoutes = {};
let courierMap = {};
let courierLastLatLng = {};

const NODE_COORDINATES = {};

async function loadGraphNodes() {
    try {
        const resp = await fetch('/api/graph/nodes');
        if (!resp.ok) throw new Error('graph nodes fetch failed');
        const data = await resp.json();
        for (const [nodeId, coords] of Object.entries(data)) {
            NODE_COORDINATES[parseInt(nodeId)] = { lat: coords.lat, lng: coords.lng };
        }
        console.log(`Loaded ${Object.keys(NODE_COORDINATES).length} graph nodes from server`);
    } catch (e) {
        console.error('Failed to load graph nodes, using fallback coords:', e);
        const centerLat = 55.75, centerLng = 37.61, step = 0.018;
        let idx = 0;
        for (let i = -2; i <= 2; i++) {
            for (let j = -2; j <= 2; j++) {
                NODE_COORDINATES[idx] = { lat: centerLat + j * step, lng: centerLng + i * step };
                idx++;
                if (idx >= 50) break;
            }
            if (idx >= 50) break;
        }
    }
}

function showToast(message, type = 'success') {
    const isDark = document.documentElement.classList.contains('dark');

    const styles = {
        background: isDark ? '#1e293b' : '#ffffff',
        color: isDark ? '#f8fafc' : '#0f172a',
        border: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
        boxShadow: isDark ? '0 4px 20px rgba(0,0,0,0.5)' : '0 4px 12px rgba(0,0,0,0.1)'
    };

    const colors = {
        success: '#10b981',
        error: '#ef4444',
        info: '#3b82f6',
        warning: '#f59e0b'
    };

    Toastify({
        text: message,
        duration: 3000,
        gravity: 'top',
        position: 'right',
        stopOnFocus: true,
        style: styles,
        avatar: type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'
    }).showToast();
}

function generateNodeCoords() {
    const centerX = 37.61,
        centerY = 55.75;
    const step = 0.01;
    let idx = 0;
    for (let i = -2; i <= 2; i++) {
        for (let j = -2; j <= 2; j++) {
            const x = centerX + i * step + Math.random() * 0.005;
            const y = centerY + j * step + Math.random() * 0.005;
            NODE_COORDINATES[idx] = {
                x,
                y
            };
            COORD_TO_NODE.set(`${x.toFixed(4)},${y.toFixed(4)}`, idx);
            idx++;
            if (idx >= 50) break;
        }
        if (idx >= 50) break;
    }
}

function nodeToLatLng(nodeId) {
    const coord = NODE_COORDINATES[nodeId];
    if (!coord) return [55.75, 37.61];
    return [coord.lat, coord.lng];
}

function xyToLatLng(x, y) {
    // Must match backend conversion in `courier_service/routes.py:get_graph_nodes`
    const CENTER_LAT = 55.75, CENTER_LNG = 37.61;
    const SCALE = 0.004;
    const OFFSET = 500;
    return [CENTER_LAT + (y - OFFSET) * SCALE, CENTER_LNG + (x - OFFSET) * SCALE];
}

function setTile(isDark) {
    if (currentTileLayer) map.removeLayer(currentTileLayer);
    currentTileLayer = L.tileLayer(isDark ? TILES.dark : TILES.light, {
        attribution: '© CARTO'
    }).addTo(map);
}

async function init() {
    await loadGraphNodes();
    map = L.map('map', {
        zoomControl: false
    }).setView([55.75, 37.61], 12);

    const startDark = document.documentElement.classList.contains('dark');
    setTile(startDark);
    updateThemeButton(startDark);

    // реклама контракта
    function replaceAttribution() {
        const el = document.querySelector('.leaflet-control-attribution');

        el.innerHTML = `
        <a href="http://xn--80aneakq8a4c.xn--p1ai/" title="A JavaScript library for interactive maps">
            <svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" 
                 width="12" height="8" viewBox="0 0 12 8" 
                 class="leaflet-attribution-flag">
                <rect width="12" height="8" fill="#FFFFFF"/>
                <rect y="2.67" width="12" height="2.66" fill="#0039A6"/>
                <rect y="5.33" width="12" height="2.67" fill="#DA291C"/>
            </svg>
            КОНТРАКТ
        </a>
        <span aria-hidden="true"> | </span>
        © РФ
    `;
    }

    // Запуск
    setInterval(replaceAttribution, 100);

    setupUI();

    // Очищаем таблицы при запуске
    document.getElementById('couriersList').innerHTML = '';
    document.getElementById('activeOrders').innerHTML = '';
    document.getElementById('historyTableBody').innerHTML = '';

    // Очищаем маркеры
    Object.values(courierMarkers).forEach(m => map.removeLayer(m));
    courierMarkers = {};
    Object.values(orderMarkers).forEach(m => map.removeLayer(m));
    orderMarkers = {};
    Object.values(orderPolylines).forEach(p => map.removeLayer(p));
    orderPolylines = {};

    loadCouriers();
    loadOrders();
    connectWebSocket();
    simulatePrometheus();

    // Периодическое обновление данных
    setInterval(() => {
        loadCouriers();
        loadOrders();
    }, 2000);
}

function setupUI() {
    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.getElementById('toggleBtn');
    const toggleIcon = document.getElementById('toggleIcon');

    toggleBtn.addEventListener('click', () => {
        const isHidden = sidebar.classList.toggle('-translate-x-full');
        toggleIcon.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
    });

    document.getElementById('themeToggle').addEventListener('click', () => {
        document.documentElement.classList.toggle('dark');
        const isDark = document.documentElement.classList.contains('dark');
        setTile(isDark);
        updateThemeButton(isDark);
    });

    document.getElementById('simulateBtn').addEventListener('click', handleSimulate);

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('tab-active'));
            btn.classList.add('tab-active');

            document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
            document.getElementById(btn.dataset.tab + 'Content').classList.remove('hidden');

            if (btn.dataset.tab === 'couriers') {
                loadCouriers();
            }
        });
    });

    document.getElementById('createOrderBtn').addEventListener('click', handleCreateOrder);
    document.getElementById('createCourierBtn').addEventListener('click', handleCreateCourier);
}

async function handleCreateOrder() {
    const start = document.getElementById('startInput').value;
    const end = document.getElementById('endInput').value;

    if (!start || !end) {
        alert("Введите оба адреса");
        return;
    }

    const restaurantNode = Math.floor(Math.random() * 50);
    const customerNode = Math.floor(Math.random() * 50);
    const customerId = "user_" + Math.floor(Math.random() * 1000);

    try {
        const resp = await fetch('/api/orders', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                restaurant_node_id: restaurantNode,
                customer_node_id: customerNode,
                customer_id: customerId
            })
        });

        if (!resp.ok) throw new Error('Failed to create order');

        const order = await resp.json();

        const restCoords = nodeToLatLng(restaurantNode);
        const custCoords = nodeToLatLng(customerNode);
        drawRoute(restCoords, custCoords, order.id);
        addOrderToList(order);

        document.getElementById('startInput').value = '';
        document.getElementById('endInput').value = '';

        loadOrders();
    } catch (e) {
        console.error('Error creating order:', e);
        alert('Ошибка создания заказа: ' + e.message);
    }
}

async function handleSimulate() {
    const btn = document.getElementById('simulateBtn');
    btn.disabled = true;
    btn.textContent = 'Запуск...';

    try {
        const resp = await fetch('/api/simulate-full', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                courier_count: 5,
                order_count: 20
            })
        });

        if (!resp.ok) throw new Error('Failed to simulate');

        const result = await resp.json();
        console.log('Simulate result:', result);

        showToast(`Создано ${result.couriers_created} курьеров и ${result.orders_created} заказов!`, 'success');

        setTimeout(() => {
            loadCouriers();
            loadOrders();
        }, 2000);
    } catch (e) {
        console.error('Error simulating:', e);
        showToast('Ошибка эмуляции: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Эмуляция';
    }
}

async function handleCreateCourier() {
    const name = document.getElementById('courierName').value;
    const startNodeId = parseInt(document.getElementById('startNodeId').value);

    if (!name) {
        alert("Введите имя курьера");
        return;
    }

    if (startNodeId < 0 || startNodeId >= 50) {
        alert("Номер узла должен быть от 0 до 49");
        return;
    }

    try {
        const resp = await fetch('/api/couriers', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: name,
                start_node_id: startNodeId
            })
        });

        if (!resp.ok) throw new Error('Failed to create courier');

        const courier = await resp.json();

        addCourierToList(courier);
        addCourierMarker(courier);

        document.getElementById('courierName').value = '';
    } catch (e) {
        console.error('Error creating courier:', e);
        alert('Ошибка создания курьера: ' + e.message);
    }
}

async function loadCouriers() {
    try {
        const resp = await fetch('/api/couriers');
        if (!resp.ok) return;
        const couriers = await resp.json();

        const container = document.getElementById('couriersList');
        container.innerHTML = '';

        couriers.forEach(courier => {
            addCourierToList(courier);
            // Не пересоздаём маркеры/линии каждые 2 сек — иначе получается "телепорт"
            // и сбивается плавное WS-движение.
            if (!courierMarkers[courier.id]) {
                addCourierMarker(courier);
            } else {
                // Fallback without WS: update marker from backend coordinates on every poll.
                if (courier.current_x !== null && courier.current_x !== undefined &&
                    courier.current_y !== null && courier.current_y !== undefined) {
                    const latlng = xyToLatLng(courier.current_x, courier.current_y);
                    courierMarkers[courier.id].setLatLng(latlng);
                    courierLastLatLng[courier.id] = latlng;
                } else {
                    const latlng = nodeToLatLng(courier.current_node_id);
                    courierMarkers[courier.id].setLatLng(latlng);
                    courierLastLatLng[courier.id] = latlng;
                }
            }

            // Если курьер idle — убираем его линию маршрута (например, после доставки).
            if (!courier.current_order_id && courierPolylines[courier.id]) {
                map.removeLayer(courierPolylines[courier.id]);
                delete courierPolylines[courier.id];
            }
            if (!courier.current_order_id && courierRoutes[courier.id]) {
                delete courierRoutes[courier.id];
            }
        });
    } catch (e) {
        console.error('Error loading couriers:', e);
    }
}

async function loadOrders() {
    try {
        const ordersResp = await fetch('/api/orders');
        if (!ordersResp.ok) return;
        const orders = await ordersResp.json();
        const activeOrderIds = new Set();
        const activeCourierIds = new Set();
        
        const couriersResp = await fetch('/api/couriers');
        const couriers = couriersResp.ok ? await couriersResp.json() : [];
        couriers.forEach(c => {
            courierMap[c.id] = c;
        });

        const container = document.getElementById('activeOrders');
        container.innerHTML = '';

        const tableBody = document.getElementById('historyTableBody');
        tableBody.innerHTML = '';

        // Для активных доставок мы будем показывать "живую" линию курьера (сокращается),
        // поэтому линии заказов рисуем только когда курьер ещё не назначен.
        Object.values(orderPolylines).forEach(p => map.removeLayer(p));
        orderPolylines = {};

        Object.values(orderMarkers).forEach(m => map.removeLayer(m));
        orderMarkers = {};

        orders.forEach(order => {
            if (order.status === 'delivered' || order.status === 'cancelled') {
                addOrderToHistory(order);
                return;
            }
            activeOrderIds.add(order.id);

            addOrderToList(order);

            const restaurantCoords = nodeToLatLng(order.restaurant_node_id);
            const restaurantIcon = L.divIcon({
                className: 'order-marker',
                html: '<div class="w-4 h-4 rounded-full bg-red-500 border-2 border-white shadow-lg"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            });
            const restaurantMarker = L.marker(restaurantCoords, {
                icon: restaurantIcon
            }).addTo(map);
            restaurantMarker.bindPopup(`<b>Ресторан</b><br>Узел: ${order.restaurant_node_id}`);
            orderMarkers[`${order.id}_restaurant`] = restaurantMarker;

            const customerCoords = nodeToLatLng(order.customer_node_id);
            const customerIcon = L.divIcon({
                className: 'order-marker',
                html: '<div class="w-4 h-4 rounded-full bg-emerald-500 border-2 border-white shadow-lg"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            });
            const customerMarker = L.marker(customerCoords, {
                icon: customerIcon
            }).addTo(map);
            customerMarker.bindPopup(`<b>Клиент</b><br>Узел: ${order.customer_node_id}`);
            orderMarkers[`${order.id}_customer`] = customerMarker;

            const courier = order.courier_id ? courierMap[order.courier_id] : null;
            const routeColor = courier ? courier.color : '#f59e0b';
            
            console.log(`Заказ ${order.id}: route =`, order.route, 'status =', order.status, 'courier =', courier);

            // Маршрут: если нет сохранённого route, делаем fallback ресторан->клиент.
            const effectiveRoute = (order.route && order.route.length > 1)
                ? order.route
                : [order.restaurant_node_id, order.customer_node_id];

            if (courier) {
                activeCourierIds.add(courier.id);
                // "Живая" линия курьера: цвет курьера, начинается от курьера и укорачивается по мере движения.
                courierRoutes[courier.id] = {
                    orderId: order.id,
                    route: effectiveRoute,
                    color: courier.color || routeColor,
                    currentIndex: 0,
                };
                syncCourierRouteIndex(courier.id, courier.current_node_id);
                redrawCourierRemainingRoute(courier.id);
            } else {
                // Курьер ещё не назначен — показываем линию заказа (пунктир), чтобы маршрут был виден.
                if (effectiveRoute && effectiveRoute.length > 1) {
                    const latlngs = effectiveRoute.map(nodeId => nodeToLatLng(nodeId));
                    const polyline = L.polyline(latlngs, {
                        color: routeColor,
                        weight: 5,
                        opacity: 0.9,
                        dashArray: '8, 10',
                        lineJoin: 'round'
                    }).addTo(map);
                    orderPolylines[order.id] = polyline;
                } else {
                    console.log(`Заказ ${order.id}: маршрут не отрисован - route =`, order.route);
                }
            }
        });

        // Удаляем линии/маршруты у курьеров, у которых больше нет активного заказа.
        Object.keys(courierRoutes).forEach((courierIdStr) => {
            const courierId = Number(courierIdStr);
            const info = courierRoutes[courierId];
            const hasActiveCourier = activeCourierIds.has(courierId);
            const hasActiveOrder = info && activeOrderIds.has(info.orderId);
            if (!hasActiveCourier || !hasActiveOrder) {
                if (courierPolylines[courierId]) {
                    map.removeLayer(courierPolylines[courierId]);
                    delete courierPolylines[courierId];
                }
                delete courierRoutes[courierId];
            }
        });
    } catch (e) {
        console.error('Error loading orders:', e);
    }
}

function syncCourierRouteIndex(courierId, nodeId) {
    const info = courierRoutes[courierId];
    if (!info || !info.route || info.route.length === 0) return;

    // Move forward only: avoid jumping to the last duplicate node in route.
    const from = Math.max(info.currentIndex || 0, 0);
    let idx = -1;
    for (let i = from; i < info.route.length; i++) {
        if (info.route[i] === nodeId) {
            idx = i;
            break;
        }
    }
    if (idx >= 0) info.currentIndex = idx;
}

function redrawCourierRemainingRoute(courierId) {
    const info = courierRoutes[courierId];
    if (!info || !info.route || info.route.length < 2) return;

    const startIdx = Math.min(info.currentIndex || 0, info.route.length - 1);
    const remaining = info.route.slice(startIdx);

    // Если остался один узел — линию убираем
    if (remaining.length < 2) {
        if (courierPolylines[courierId]) {
            map.removeLayer(courierPolylines[courierId]);
            delete courierPolylines[courierId];
        }
        return;
    }

    // Route starts from courier current position and then to the NEXT route points.
    // This way line shortens smoothly while moving between nodes.
    const head = courierLastLatLng[courierId] || nodeToLatLng(remaining[0]);
    const tailNodes = remaining.slice(1);
    const tail = tailNodes.map(n => nodeToLatLng(n));
    const latlngs = [head, ...tail];

    if (latlngs.length < 2) {
        if (courierPolylines[courierId]) {
            map.removeLayer(courierPolylines[courierId]);
            delete courierPolylines[courierId];
        }
        return;
    }
    const color = info.color || '#22c55e';

    if (courierPolylines[courierId]) {
        map.removeLayer(courierPolylines[courierId]);
    }

    courierPolylines[courierId] = L.polyline(latlngs, {
        color: color,
        weight: 6,
        opacity: 0.95,
        lineJoin: 'round'
    }).addTo(map);
}

function addCourierToList(courier) {
    const container = document.getElementById('couriersList');
    const color = courier.color || '#22c55e';

    const statusColors = {
        idle: 'bg-slate-100 dark:bg-slate-800 text-slate-500',
        pending: 'bg-amber-100 dark:bg-amber-500/20 text-amber-600',
        delivering: 'bg-blue-100 dark:bg-blue-500/20 text-blue-600',
        busy: 'bg-purple-100 dark:bg-purple-500/20 text-purple-600'
    };

    const html = `
        <div class="courier-item p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 cursor-pointer hover:border-indigo-500 transition-colors" data-courier-id="${courier.id}">
            <div class="flex justify-between items-start mb-2">
                <span class="text-xs font-bold" style="color: ${color}">${courier.name}</span>
                <span class="text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-tighter ${statusColors[courier.status] || statusColors.idle}">${courier.status}</span>
            </div>
            <p class="text-[11px] text-slate-500 dark:text-slate-400">Узел: ${courier.current_node_id}</p>
            ${courier.current_order_id ? `<p class="text-[11px] text-indigo-500">Заказ #${courier.current_order_id}</p>` : ''}
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
}

function addCourierMarker(courier) {
    const latlng = nodeToLatLng(courier.current_node_id);
    const color = courier.color || '#22c55e';

    const icon = L.divIcon({
        className: 'courier-marker',
        html: `<div class="w-8 h-8 rounded-full border-2 border-white shadow-lg flex items-center justify-center text-white text-xs font-bold" style="background-color: ${color}">${courier.name.charAt(0)}</div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16]
    });

    const marker = L.marker(latlng, {
        icon
    }).addTo(map);
    marker.bindPopup(`<b>${courier.name}</b><br>Статус: ${courier.status}<br>Узел: ${courier.current_node_id}<br>Цвет: <span style="color: ${color}">■</span>`);

    courierMarkers[courier.id] = marker;
    courierLastLatLng[courier.id] = latlng;
}

function updateCourierPosition(courierId, nodeId, x = null, y = null) {
    if (courierMarkers[courierId]) {
        const latlng = (x !== null && y !== null) ? xyToLatLng(x, y) : nodeToLatLng(nodeId);
        courierMarkers[courierId].setLatLng(latlng);
        courierMarkers[courierId].setPopupContent(`Курьер на узле ${nodeId}`);
        courierLastLatLng[courierId] = latlng;
    }
    
    // Обновляем индекс на основе фактического nodeId и рисуем ОСТАТОК маршрута (линия "укорачивается")
    if (courierRoutes[courierId] && courierRoutes[courierId].route) {
        syncCourierRouteIndex(courierId, nodeId);
        redrawCourierRemainingRoute(courierId);
    }
}

function addOrderToList(order) {
    const container = document.getElementById('activeOrders');

    const statusLabels = {
        pending: 'Ожидает',
        assigned: 'Назначен',
        in_progress: 'В пути',
        delivered: 'Доставлен',
        cancelled: 'Отменён'
    };

    const statusColors = {
        pending: 'bg-amber-100 dark:bg-amber-500/20 text-amber-600',
        assigned: 'bg-blue-100 dark:bg-blue-500/20 text-blue-600',
        in_progress: 'bg-indigo-100 dark:bg-indigo-500/20 text-indigo-600',
        delivered: 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-600',
        cancelled: 'bg-red-100 dark:bg-red-500/20 text-red-600'
    };

    const html = `
        <div class="order-item group p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800" id="order-card-${order.id}">
            <div class="flex justify-between items-start mb-2">
                <span class="text-xs font-bold text-indigo-500">Заказ #${order.id}</span>
                <span class="text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-tighter ${statusColors[order.status] || statusColors.pending}">${statusLabels[order.status] || order.status}</span>
            </div>
            <p class="text-[11px] text-slate-500 dark:text-slate-400">Узел ресторана: ${order.restaurant_node_id} → Узел клиента: ${order.customer_node_id}</p>
            ${order.courier_id ? `<p class="text-[11px] text-emerald-500">Курьер: #${order.courier_id}</p>` : ''}
        </div>
    `;
    container.insertAdjacentHTML('afterbegin', html);

    addOrderToHistory(order);
}

function addOrderToHistory(order) {
    const statusLabels = {
        pending: 'Ожидает',
        assigned: 'Назначен',
        in_progress: 'В пути',
        delivered: 'Доставлен',
        cancelled: 'Отменён'
    };

    const statusTextColors = {
        pending: 'text-amber-600 dark:text-amber-400',
        assigned: 'text-blue-600 dark:text-blue-400',
        in_progress: 'text-indigo-600 dark:text-indigo-400',
        delivered: 'text-emerald-600 dark:text-emerald-400',
        cancelled: 'text-red-600 dark:text-red-400'
    };

    const tableBody = document.getElementById('historyTableBody');
    const row = `
        <tr class="hover:bg-slate-50 dark:hover:bg-slate-900 transition-colors">
            <td class="py-3 px-2 font-mono">#${order.id}</td>
            <td class="py-3 px-2 font-bold uppercase text-[9px] ${statusTextColors[order.status] || statusTextColors.pending}">${statusLabels[order.status] || order.status}</td>
            <td class="py-3 px-2 text-right text-slate-400">0</td>
        </tr>
    `;
    tableBody.insertAdjacentHTML('afterbegin', row);
}

function removeOrderFromMap(orderId) {
    // Убираем маркеры
    ['restaurant', 'customer'].forEach(type => {
        const key = `${orderId}_${type}`;
        if (orderMarkers[key]) {
            map.removeLayer(orderMarkers[key]);
            delete orderMarkers[key];
        }
    });
    // Убираем маршрут
    if (orderPolylines[orderId]) {
        map.removeLayer(orderPolylines[orderId]);
        delete orderPolylines[orderId];
    }
    // Убираем карточку
    const card = document.getElementById(`order-card-${orderId}`);
    if (card) card.remove();
}

function drawRoute(start, end, orderId) {
    if (orderPolylines[orderId]) {
        map.removeLayer(orderPolylines[orderId]);
    }

    const polyline = L.polyline([start, end], {
        color: '#6366f1',
        weight: 6,
        opacity: 0.8,
        dashArray: '10, 10',
        lineJoin: 'round'
    }).addTo(map);

    orderPolylines[orderId] = polyline;
    map.fitBounds(polyline.getBounds(), {
        padding: [100, 100]
    });
}

function connectWebSocket() {
    const wsUrl = `ws://${window.location.host}/ws`;
    let ws;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            const statusEl = document.getElementById('wsStatus');
            statusEl.classList.remove('bg-red-500', 'bg-amber-500');
            statusEl.classList.add('bg-emerald-500', 'shadow-[0_0_8px_#10b981]');
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWSMessage(data);
            } catch (e) {
                console.log('WS message:', event.data);
            }
        };

        ws.onerror = (e) => {
            console.log('WebSocket error:', e);
            const statusEl = document.getElementById('wsStatus');
            statusEl.classList.remove('bg-emerald-500', 'shadow-[0_0_8px_#10b981]');
            statusEl.classList.add('bg-amber-500');
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            const statusEl = document.getElementById('wsStatus');
            statusEl.classList.remove('bg-emerald-500', 'shadow-[0_0_8px_#10b981]');
            statusEl.classList.add('bg-red-500');
            setTimeout(() => connectWebSocket(), 3000);
        };
    } catch (e) {
        console.error('WebSocket connection failed:', e);
    }

    connectOrderWS();
}

function connectOrderWS() {
    const wsUrl = `ws://${window.location.host}/api/orders/ws/web_client`;
    let orderWs;

    try {
        orderWs = new WebSocket(wsUrl);

        orderWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleOrderWSMessage(data);
            } catch (e) {
                console.log('Order WS message:', event.data);
            }
        };
    } catch (e) {
        console.log('Order WebSocket not available');
    }
}

function handleWSMessage(data) {
    console.log('WS message:', data);
    if (data.type === 'coordinate') {
        updateCourierPosition(data.courier_id, data.node_id, data.x, data.y);
    } else if (data.type === 'order_delivered') {
        handleOrderDelivered(data.order_id, data.courier_id);
    }
}

function handleOrderWSMessage(data) {
    if (data.type === 'order_delivered') {
        handleOrderDelivered(data.order_id, data.courier_id);
    } else if (data.type === 'order_update') {
        loadOrders();
    }
}

function handleOrderDelivered(orderId, courierId) {
    // Убираем с карты
    removeOrderFromMap(orderId);
    // Убираем "живую" линию курьера
    if (courierId && courierPolylines[courierId]) {
        map.removeLayer(courierPolylines[courierId]);
        delete courierPolylines[courierId];
    }
    if (courierId && courierRoutes[courierId]) {
        delete courierRoutes[courierId];
    }
    // Тост уведомление
    showToast(`✅ Заказ #${orderId} доставлен${courierId ? ` курьером #${courierId}` : ''}!`, 'success');
    // Обновляем таблицу истории
    loadOrders();
}

function updateThemeButton(isDark) {
    const btn = document.getElementById('themeToggle');
    btn.textContent = isDark ? 'Light Mode' : 'Dark Mode';
}

function simulatePrometheus() {
    setInterval(() => {
        document.getElementById('opsVal').innerText = (0.3 + Math.random() * 0.5).toFixed(2);
        document.getElementById('etaVal').innerText = Math.floor(15 + Math.random() * 20) + 'm';
    }, 2500);
}

document.addEventListener('DOMContentLoaded', init);