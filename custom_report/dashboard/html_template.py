"""
ECharts HTML/JS 模板生成器 — 简化版

生成完整的仪表盘 HTML 页面字符串。
使用字符串拼接而非 f-string 嵌套，避免转义问题。
"""

import json
from pathlib import Path


def build_dashboard_html(dashboard_config: dict, use_cdn: bool = False, embed_data: bool = True, echarts_dir: str = '') -> str:
    """生成完整的仪表盘 HTML 页面

    Args:
        echarts_dir: echarts 资源目录的本地路径（非 CDN 模式时生成绝对 file:// URL）
    """
    config_json = json.dumps(dashboard_config, ensure_ascii=False)

    if use_cdn:
        echarts_src = 'https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js'
        qwebchannel_src = 'https://cdn.jsdelivr.net/npm/qwebchannel@6.2.0/qwebchannel.js'
    else:
        # 使用绝对 file:// URL，不依赖 base_url 的目录斜杠判断
        echarts_src = Path(echarts_dir, 'echarts.min.js').as_uri() if echarts_dir else './echarts/echarts.min.js'
        qwebchannel_src = 'qrc:///qtwebchannel/qwebchannel.js'

    theme = dashboard_config.get('theme', 'light')
    dark_class = 'dark' if theme == 'dark' else ''

    parts = []
    parts.append('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
''')
    parts.append(f'<script src="{echarts_src}"></script>\n')
    parts.append(f'<script src="{qwebchannel_src}"></script>\n')
    # ECharts 插件：词云、水球、3D
    for plugin in ('echarts-wordcloud.min.js', 'echarts-liquidfill.min.js', 'echarts-gl.min.js'):
        plugin_path = Path(echarts_dir, plugin)
        if plugin_path.exists():
            parts.append(f'<script src="{plugin_path.as_uri()}"></script>\n')
    parts.append('''<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: "Microsoft YaHei", sans-serif; background:#F0F2F5; overflow-y:auto; }
body.dark { background:#1A1A2E; }
.grid { display:grid; gap:1px; padding:16px; min-height:100vh; }
.grid.show-lines { background: linear-gradient(to right, #E0E0E0 1px, transparent 1px), linear-gradient(to bottom, #E0E0E0 1px, transparent 1px); }
.grid.show-lines.dark { background: linear-gradient(to right, #444 1px, transparent 1px), linear-gradient(to bottom, #444 1px, transparent 1px); }
.card { background:#FFF; border-radius:4px; box-shadow:0 0 0 3px #F0F2F5; position:relative; overflow:hidden; display:flex; flex-direction:column; min-height:280px; }
body.dark .card { background:#16213E; }
.card .hd { padding:10px 16px 4px; font-size:14px; font-weight:600; color:#333; flex-shrink:0; }
body.dark .card .hd { color:#E0E0E0; }
.card .bd { flex:1; min-height:200px; width:100%; }
.card.selected { box-shadow:0 0 0 2px #FF8C00; }
.kpi { display:flex; flex-direction:column; align-items:center; justify-content:center; padding:16px; }
.kpi .v { font-size:36px; font-weight:bold; color:#FF8C00; }
.kpi .l { font-size:14px; color:#999; margin-top:4px; }
.tbl { padding:8px 16px; overflow:auto; }
.tbl table { width:100%; border-collapse:collapse; font-size:13px; }
.tbl th { background:#FAFAFA; padding:8px 12px; text-align:left; border-bottom:2px solid #E8E8E8; position:sticky; top:0; }
.tbl td { padding:6px 12px; border-bottom:1px solid #F0F0F0; }
.placeholder { border:2px dashed #D9D9D9; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#999; font-size:14px; cursor:pointer; min-height:280px; }
.drill-nav { padding:4px 16px; font-size:12px; }
.drill-nav span { color:#1890FF; cursor:pointer; }
.drill-nav span:hover { text-decoration:underline; }
</style>
</head>
<body class="''' + dark_class + '''">
<div class="grid" id="grid"></div>
<script>
var CONFIG = ''' + config_json + ''';
var ALL_DATA = {};
var chartInstances = {};
var crossFilterState = {};
var _initialized = false;

function initCharts() {
    if (_initialized) return;
    _initialized = true;
    var grid = document.getElementById('grid');
    var cols = CONFIG.grid_columns || 3;
    var rowH = CONFIG.grid_row_height || 320;
    grid.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';
    grid.style.gridAutoRows = rowH + 'px';
    // 网格背景大小（虚线对齐）
    grid.style.backgroundSize = (100/cols) + '% ' + rowH + 'px';

    (CONFIG.charts || []).forEach(function(c) {
        var card = document.createElement('div');
        card.className = 'card';
        card.id = 'chart-' + c.id;
        var pos = c.position || [0,0];
        var sz = c.size || [1,1];
        card.style.gridRow = (pos[0]+1) + ' / span ' + sz[0];
        card.style.gridColumn = (pos[1]+1) + ' / span ' + sz[1];
        card._rowSpan = sz[0];
        card._colSpan = sz[1];
        card._chartId = c.id;

        var hd = document.createElement('div');
        hd.className = 'hd';
        hd.textContent = c.title || '';
        hd.style.cursor = 'grab';
        card.appendChild(hd);

        var bd = document.createElement('div');
        bd.className = 'bd';
        card.appendChild(bd);

        // ====== 拖动标题栏移动图表（使用实时 DOM 尺寸，避免 stale config）======
        var dragInfo = null;
        hd.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            e.stopPropagation();
            e.preventDefault();
            var cols = CONFIG.grid_columns || 3;
            var rowH = CONFIG.grid_row_height || 320;
            var colW = grid.offsetWidth / cols;
            // 用 DOM 上实时的行列跨度（resize 更新的），而非 CONFIG 中的可能过时的值
            var curRowSpan = card._rowSpan || sz[0] || 1;
            var curColSpan = card._colSpan || sz[1] || 1;
            dragInfo = {
                startX: e.clientX, startY: e.clientY,
                origRow: pos[0], origCol: pos[1],
                rowSpan: curRowSpan, colSpan: curColSpan,
                colW: colW, rowH: rowH, cols: cols
            };
            card.style.zIndex = '100';
            card.style.opacity = '0.85';
            hd.style.cursor = 'grabbing';
            window._isDragging = true;
        });

        document.addEventListener('mousemove', function(e) {
            if (!dragInfo) return;
            var dx = e.clientX - dragInfo.startX;
            var dy = e.clientY - dragInfo.startY;
            var newCol = Math.max(0, Math.min(dragInfo.cols - Math.ceil(dragInfo.colSpan),
                Math.round(dragInfo.origCol + dx / dragInfo.colW)));
            var newRow = Math.max(0, Math.round(dragInfo.origRow + dy / dragInfo.rowH));
            card.style.gridRow = (newRow+1) + ' / span ' + dragInfo.rowSpan;
            card.style.gridColumn = (newCol+1) + ' / span ' + dragInfo.colSpan;
        });

        document.addEventListener('mouseup', function(e) {
            if (!dragInfo) return;
            var newRow = parseInt(card.style.gridRow) - 1;
            var newCol = parseInt(card.style.gridColumn) - 1;
            if (isNaN(newRow)) newRow = dragInfo.origRow;
            if (isNaN(newCol)) newCol = dragInfo.origCol;
            pos[0] = Math.max(0, newRow);
            pos[1] = Math.max(0, newCol);
            card.style.gridRow = (pos[0]+1) + ' / span ' + dragInfo.rowSpan;
            card.style.gridColumn = (pos[1]+1) + ' / span ' + dragInfo.colSpan;
            card.style.zIndex = '';
            card.style.opacity = '';
            hd.style.cursor = 'grab';
            if (window.bridge) {
                window.bridge.handle_js_action('chart_move', JSON.stringify({chartId: c.id, position: [pos[0], pos[1]]}));
            }
            dragInfo = null;
            setTimeout(function(){ window._isDragging = false; }, 300);
        });

        // ====== 右下角调整大小（固定位置，仅改跨度）======
        var resizeHandle = document.createElement('div');
        resizeHandle.style.cssText =
            'position:absolute;right:0;bottom:0;width:28px;height:28px;'
            + 'cursor:nwse-resize;z-index:100;'
            + 'border-radius:0 0 4px 0;'
            + 'display:flex;align-items:flex-end;justify-content:flex-end;';
        resizeHandle.innerHTML =
            '<svg width="16" height="16" viewBox="0 0 16 16" style="pointer-events:none;opacity:0.5;">'
            + '<path d="M14 2 L14 6 L10 2 Z M14 10 L14 14 L10 14 L6 10 Z" fill="#999"/>'
            + '</svg>';
        resizeHandle.title = '拖拽调整大小';
        var resizeInfo = null;

        resizeHandle.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            e.stopPropagation();
            e.preventDefault();
            var cols = CONFIG.grid_columns || 3;
            var rowH = CONFIG.grid_row_height || 320;
            var colW = grid.offsetWidth / cols;
            // 固定位置：用 grid-row-start / grid-column-start 锁住位置
            var curRowStart = pos[0] + 1;
            var curColStart = pos[1] + 1;
            card.style.gridRow = curRowStart + ' / span ' + (card._rowSpan || 1);
            card.style.gridColumn = curColStart + ' / span ' + (card._colSpan || 1);
            resizeInfo = {
                startX: e.clientX, startY: e.clientY,
                startColSpan: card._colSpan || 1, startRowSpan: card._rowSpan || 1,
                colW: colW, rowH: rowH, cols: cols,
                rowStart: curRowStart, colStart: curColStart,
            };
            window._isResizing = true;
            card.style.zIndex = '50';
        });

        document.addEventListener('mousemove', function(e) {
            if (!resizeInfo) return;
            e.preventDefault();
            var dCol = (e.clientX - resizeInfo.startX) / resizeInfo.colW;
            var dRow = (e.clientY - resizeInfo.startY) / resizeInfo.rowH;
            var newColSpan = Math.max(1, Math.round(resizeInfo.startColSpan + dCol));
            var newRowSpan = Math.max(1, Math.round(resizeInfo.startRowSpan + dRow));
            newColSpan = Math.min(newColSpan, resizeInfo.cols - (resizeInfo.colStart - 1));
            // 仅改跨度，不改起始位置
            card.style.gridRow = resizeInfo.rowStart + ' / span ' + newRowSpan;
            card.style.gridColumn = resizeInfo.colStart + ' / span ' + newColSpan;
        });

        document.addEventListener('mouseup', function(e) {
            if (!resizeInfo) return;
            var newColSpan = Math.max(1, Math.min(resizeInfo.cols,
                Math.round((card._colSpan || resizeInfo.startColSpan))));
            var newRowSpan = Math.max(1, Math.round(card._rowSpan || resizeInfo.startRowSpan));
            // 从 DOM 读取实际吸附结果
            var gridRowVal = card.style.gridRow;
            var gridColVal = card.style.gridColumn;
            // 解析 span 值
            var matchR = gridRowVal.match(/span\\s+(\\d+)/);
            var matchC = gridColVal.match(/span\\s+(\\d+)/);
            if (matchC) newColSpan = Math.max(1, parseInt(matchC[1]));
            if (matchR) newRowSpan = Math.max(1, parseInt(matchR[1]));
            card.style.gridRow = resizeInfo.rowStart + ' / span ' + newRowSpan;
            card.style.gridColumn = resizeInfo.colStart + ' / span ' + newColSpan;
            card._rowSpan = newRowSpan;
            card._colSpan = newColSpan;
            card.style.zIndex = '';
            if (window.bridge) {
                window.bridge.handle_js_action('chart_resize', JSON.stringify({chartId: c.id, size: [newRowSpan, newColSpan]}));
            }
            var inst = chartInstances[c.id];
            if (inst && !inst.isDisposed()) { try { inst.resize(); } catch(x){} }
            resizeInfo = null;
            setTimeout(function(){ window._isResizing = false; }, 300);
        });

        card.appendChild(resizeHandle);
        grid.appendChild(card);

        renderWidget(c, bd, ALL_DATA[c.id] || []);

        // 单击选中（resize/drag 后 300ms 内忽略）
        card.addEventListener('click', function(e) {
            if (dragInfo || resizeInfo || window._isResizing || window._isDragging) return;
            e.stopPropagation();
            selectChartCard(c.id);
        });

        // 右键菜单
        card.addEventListener('contextmenu', function(e) {
            e.preventDefault();
            e.stopPropagation();
            selectChartCard(c.id);
            showChartContextMenu(e.clientX, e.clientY, c.id, c.title);
        });

        // 双击全屏
        card.addEventListener('dblclick', function(e) {
            if (window._isDragging || window._isResizing) return;
            toggleFullscreen(card, c.id);
        });
    });

    // 图表联动：共享 tooltip 十字准星
    connectAllCharts();

    // 全局键盘快捷键
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F5') {
            e.preventDefault();
            if (window.bridge) bridge.handle_js_action('change_query', '{}');
        }
        if (e.key === 'Escape') {
            var fs = document.querySelector('.card.fullscreen');
            if (fs) { fs.classList.remove('fullscreen'); fs.style.cssText = ''; }
            Object.values(chartInstances).forEach(function(i){ try{i.resize();}catch(x){} });
        }
    });
}

// ===== 图表联动 =====
function connectAllCharts() {
    var ids = [];
    for (var k in chartInstances) {
        var inst = chartInstances[k];
        if (inst && !inst.isDisposed()) {
            inst.group = 'dashboard';
            ids.push(inst.id);
        }
    }
    if (ids.length > 1) {
        try { echarts.connect('dashboard'); } catch(e) {}
    }
}

// ===== 全屏切换（保存/恢复原始 grid 位置和大小） =====
function toggleFullscreen(card, chartId) {
    var bd = card.querySelector('.bd');
    if (card.classList.contains('fullscreen')) {
        // 退出全屏 → 精确恢复到原始 grid 位置和跨度
        card.classList.remove('fullscreen');
        var orig = card._fullscreenRestore;
        if (orig) {
            card.style.cssText = '';
            card.style.gridRow = orig.gridRow;
            card.style.gridColumn = orig.gridColumn;
            card._rowSpan = orig.rowSpan;
            card._colSpan = orig.colSpan;
            card._fullscreenRestore = null;
        }
        setTimeout(function(){
            var inst = chartInstances[chartId];
            if (inst && !inst.isDisposed()) inst.resize();
        }, 100);
    } else {
        // 进入全屏 → 保存当前 grid 状态以便恢复
        card._fullscreenRestore = {
            gridRow: card.style.gridRow,
            gridColumn: card.style.gridColumn,
            rowSpan: card._rowSpan,
            colSpan: card._colSpan,
        };
        card.classList.add('fullscreen');
        card.style.cssText = 'position:fixed;top:16px;left:16px;'
            + 'width:calc(100vw - 32px);height:calc(100vh - 32px);z-index:9999;';
        setTimeout(function(){
            var inst = chartInstances[chartId];
            if (inst && !inst.isDisposed()) inst.resize();
        }, 200);
    }
}

function selectChartCard(chartId) {
    document.querySelectorAll('.card.selected').forEach(function(el){ el.classList.remove('selected'); });
    var card = document.getElementById('chart-' + chartId);
    if (card) card.classList.add('selected');
    if (window.bridge) {
        window.bridge.handle_js_action('chart_selected', JSON.stringify({chartId: chartId}));
    }
}

var _contextMenu = null;
var _ctxMenuSkip = false;
function showChartContextMenu(x, y, chartId, title) {
    if (_contextMenu) { _contextMenu.remove(); _contextMenu = null; }
    var menu = document.createElement('div');
    menu.className = 'ctx-menu';
    menu.style.cssText = 'position:fixed;left:'+x+'px;top:'+y+'px;background:#FFF;border:1px solid #D9D9D9;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.15);z-index:9999;min-width:140px;font-size:13px;';
    menu.innerHTML = '<div style="padding:4px 12px;color:#999;font-size:11px;border-bottom:1px solid #F0F0F0;">'+title+'</div>'
        + '<div class="ctx-item" data-action="remove" style="padding:8px 12px;cursor:pointer;">🗑 删除图表</div>';

    var close = function() {
        if (menu.parentNode) { menu.remove(); }
        _contextMenu = null;
        document.removeEventListener('mousedown', onMouseDown, true);
    };

    menu.querySelector('.ctx-item').addEventListener('mousedown', function(e){
        e.stopPropagation();
        e.preventDefault();
        close();
        if (window.bridge) {
            window.bridge.handle_js_action('chart_remove', JSON.stringify({chartId: chartId}));
        }
    });

    function onMouseDown(e) {
        if (_ctxMenuSkip) { _ctxMenuSkip = false; return; }
        if (!menu.contains(e.target)) {
            close();
        }
    }

    document.body.appendChild(menu);
    _contextMenu = menu;
    _ctxMenuSkip = true;
    document.addEventListener('mousedown', onMouseDown, true);
}

function renderWidget(c, el, data) {
    try {
        // card / table 优先用 Python 端预渲染的 HTML
        if (c.chart_type === 'card') {
            if (c._prerendered_html) { el.innerHTML = c._prerendered_html; return; }
            return renderKPI(c, el, data);
        }
        if (c.chart_type === 'table') {
            if (c._prerendered_html) { el.innerHTML = c._prerendered_html; return; }
            return renderTable(c, el, data);
        }
        if (typeof echarts === 'undefined') {
            el.innerHTML = '<div style="color:#FF4D4F;padding:20px;text-align:center;">❌ ECharts 库未加载<br><small>检查 echarts.min.js 路径</small></div>';
            return;
        }
        if (!data || !data.length) {
            el.innerHTML = '<div style="color:#999;padding:20px;text-align:center;">📭 暂无数据<br><small>请刷新数据或检查数据源</small></div>';
            return;
        }
        // 地图类需要先加载 GeoJSON
        if (c.chart_type === 'map_china') {
            loadChinaMap(function() { renderECharts(c, el, data); });
            return;
        }
        renderECharts(c, el, data);
    } catch(e) {
        el.innerHTML = '<div style="color:#FF4D4F;padding:16px;text-align:center;font-size:13px;">❌ ' + (c.title||'图表') + ' 渲染失败<br><small>' + e.message + '</small></div>';
    }
}

function renderECharts(c, el, data) {
    var inst = echarts.init(el);
    // 优先使用 Python 端 pyecharts 预渲染的 ECharts option
    if (c._echarts_option) {
        try {
            // _echarts_option 可能是 JSON 字符串（来自 CONFIG）或 JS 对象（来自直接推送）
            var opt = (typeof c._echarts_option === 'string')
                ? eval('(' + c._echarts_option + ')')
                : c._echarts_option;
            inst.setOption(opt, {notMerge: true});
        } catch(e) {
            if (c.chart_type === 'sankey') {
                el.innerHTML = '<div style=\"color:#FF9800;padding:20px;text-align:center;\">'
                    + '⚠ Sankey 数据存在循环引用<br><small>已自动过滤，请检查数据源</small></div>';
                return;
            }
            inst.setOption(buildOption(c, data));
        }
    } else {
        inst.setOption(buildOption(c, data));
    }
    inst.on('click', function(p) { onChartClick(c.id, p); });
    chartInstances[c.id] = inst;
}

var _chinaMapLoaded = false;
var _chinaMapCallbacks = [];
function loadChinaMap(callback) {
    if (_chinaMapLoaded) { callback(); return; }
    _chinaMapCallbacks.push(callback);
    // 优先使用 Python 端嵌入的 GeoJSON 数据
    if (window._CHINA_GEO) {
        echarts.registerMap('china', window._CHINA_GEO);
        _chinaMapLoaded = true;
        _chinaMapCallbacks.forEach(function(cb){ cb(); });
        _chinaMapCallbacks = [];
    } else {
        // 回退：尝试 fetch（导出 HTML 用）
        if (typeof fetch !== 'undefined') {
            fetch('./china.json').then(function(r){ return r.json(); }).then(function(geo){
                echarts.registerMap('china', geo);
                _chinaMapLoaded = true;
                _chinaMapCallbacks.forEach(function(cb){ cb(); });
                _chinaMapCallbacks = [];
            }).catch(function(){
                _chinaMapCallbacks.forEach(function(cb){ cb(); });
                _chinaMapCallbacks = [];
            });
        } else {
            _chinaMapCallbacks.forEach(function(cb){ cb(); });
            _chinaMapCallbacks = [];
        }
    }
}

function buildOption(c, data) {
    if (!c) return {};
    var xF = c.x_field || '';
    var yfArr = Array.isArray(c.y_fields) ? c.y_fields : [];
    var yF = yfArr[0] || '';
    var cF = c.color_field || '';
    data = Array.isArray(data) ? data : [];
    var categories = [];
    var seen = {};
    data.forEach(function(r) { var v = r[xF]||''; if (!seen[v]) { seen[v]=true; categories.push(v); } });

    function seriesData(field) {
        return categories.map(function(cat) {
            var row = data.find(function(r) { return (r[xF]||'') === cat; });
            return row ? (row[field] || 0) : 0;
        });
    }

    function pieData(nameF, valF) {
        return data.map(function(r) { return { name: r[nameF]||'', value: r[valF]||0 }; });
    }

    var type = c.chart_type;
    var base = {
        tooltip: { trigger: type==='pie' ? 'item' : 'axis' },
        legend: { show: (c.style_config||{}).show_legend!==false, bottom:0, type:'scroll' },
        grid: { left:50, right:30, top:20, bottom:40 },
        animationDuration: 300
    };

    if (type === 'pie') {
        return {
            tooltip: { trigger: 'item' },
            legend: { show: (c.style_config||{}).show_legend!==false, bottom:0 },
            series: [{ type:'pie', radius:['35%','65%'], center:['50%','45%'], data: pieData(xF, yF),
                label: { show: (c.style_config||{}).show_label===true } }]
        };
    }
    if (type === 'gauge') {
        var v = data.length ? (data[0][yF] || 0) : 0;
        return { series: [{ type:'gauge', radius:'85%', center:['50%','55%'],
            startAngle:210, endAngle:-30, min:0, max: Math.max(v*1.5, 100),
            data: [{ value: v, name: c.title||'' }] }] };
    }
    if (type === 'funnel') {
        return { tooltip:{trigger:'item'}, series:[{ type:'funnel', left:'10%',width:'80%',
            data: pieData(xF, yF).sort(function(a,b){ return b.value-a.value; }), sort:'descending' }] };
    }
    if (type === 'radar') {
        var indicators = data.map(function(r){ return { name:r[xF]||'', max: Math.max.apply(null,data.map(function(d){ return d[yF]||0; }))*1.2 }; });
        return { radar:{ indicator:indicators, center:['50%','50%'], radius:'65%' },
            series:[{ type:'radar', data:[{ value: data.map(function(r){ return r[yF]||0; }), name: c.title||'' }] }] };
    }
    if (type === 'treemap') {
        return { tooltip:{trigger:'item'}, series:[{ type:'treemap', data: pieData(xF, yF) }] };
    }
    if (type === 'map_china') {
        var mapData = data.map(function(r){ return { name: r[xF]||'', value: r[yF]||0 }; });
        var maxVal = Math.max.apply(null, mapData.map(function(d){ return d.value; }));
        return { tooltip:{trigger:'item'}, visualMap:{ min:0, max:maxVal||100, left:'left', bottom:10, text:['高','低'], calculable:true },
            series:[{ type:'map', map:'china', roam:true, data:mapData, label:{show:true,fontSize:10} }] };
    }
    if (type === 'sunburst') {
        return { tooltip:{trigger:'item'}, series:[{ type:'sunburst', data: pieData(xF, yF), radius:['15%','80%'] }] };
    }
    if (type === 'heatmap') {
        var hx = Array.from(new Set(data.map(function(r){ return r[xF]||''; })));
        var hy = Array.from(new Set(data.map(function(r){ return r[cF||yF]||''; })));
        var hmData = data.map(function(r){ return [hx.indexOf(r[xF]||''), hy.indexOf(r[cF||yF]||''), r[yF]||0]; });
        return { tooltip:{}, grid:{left:80,right:20,top:20,bottom:40},
            xAxis:{ type:'category', data:hx, splitArea:{show:true} },
            yAxis:{ type:'category', data:hy, splitArea:{show:true} },
            visualMap:{ min:0, max:Math.max.apply(null,hmData.map(function(d){return d[2];})), calculable:true, orient:'horizontal', left:'center', bottom:0 },
            series:[{ type:'heatmap', data:hmData, label:{show:true} }] };
    }
    if (type === 'sankey') {
        var links = data.map(function(r){ return { source: r[xF]||'', target: r[cF||'']||'', value: r[yF]||0 }; });
        return { tooltip:{trigger:'item'}, series:[{ type:'sankey', layout:'none', data: pieData(xF, yF), links:links }] };
    }
    if (type === 'word_cloud') {
        return { tooltip:{}, series:[{ type:'wordCloud', shape:'circle', width:'90%', height:'90%',
            data: data.map(function(r){ return { name: r[xF]||'', value: r[yF]||0 }; }) }] };
    }
    if (type === 'scatter' || type === 'effect_scatter') {
        var scData = data.map(function(r){ return [r[xF]||0, r[yF]||0]; });
        return { xAxis:{}, yAxis:{}, series:[{ type:type==='effect_scatter'?'effectScatter':'scatter', data:scData,
            symbolSize: function(d){ return (c.size_field && data[0] && data[0][c.size_field]) ? (d[2]||10) : 10; } }] };
    }
    if (type === 'calendar') {
        var calData = [];
        data.forEach(function(r){
            var d = r[xF], v = r[yF];
            if (d != null && v != null) {
                calData.push([String(d), Number(v) || 0]);
            }
        });
        if (!calData.length) {
            return { title:{text:'无有效日期数据',left:'center',top:'center'} };
        }
        var calMax = Math.max.apply(null, calData.map(function(d){ return d[1]; }));
        var firstDate = String(calData[0][0] || '');
        var rangeYear = firstDate.length >= 4 ? firstDate.substring(0,4) : '2024';
        return { tooltip:{}, visualMap:{ min:0, max:calMax||100, orient:'horizontal', left:'center', bottom:0 },
            calendar:{ range: rangeYear, cellSize:['auto',20] },
            series:[{ type:'heatmap', coordinateSystem:'calendar', data:calData }] };
    }
    if (type === 'graph') {
        var nodes = []; var nSeen = {};
        data.forEach(function(r){ var n=r[xF]||''; if(!nSeen[n]){ nSeen[n]=true; nodes.push({name:n}); } });
        data.forEach(function(r){ var n=r[cF||'']||''; if(n&&!nSeen[n]){ nSeen[n]=true; nodes.push({name:n}); } });
        var lnks = data.map(function(r){ return { source: r[xF]||'', target: r[cF||'']||'', value: r[yF]||0 }; });
        return { tooltip:{}, series:[{ type:'graph', layout:'force', roam:true, data:nodes, links:lnks,
            force:{ repulsion:200, edgeLength:100 } }] };
    }
    if (type === 'tree') {
        function buildTree(items, parentField, nameField) {
            var map = {}, roots = [];
            items.forEach(function(r){ map[r[nameField]||''] = { name: r[nameField]||'', value: r[yF]||0, children:[] }; });
            items.forEach(function(r){ var p=r[parentField]||'', n=r[nameField]||'';
                if(p && map[p] && map[n]) map[p].children.push(map[n]); else if(map[n]) roots.push(map[n]); });
            return roots.length ? roots[0] : { name:'root', children: Object.values(map) };
        }
        var treeData = buildTree(data, cF||'pid', xF);
        return { tooltip:{trigger:'item'}, series:[{ type:'tree', data:[treeData], orient:'TB', roam:true,
            top:'5%', left:'10%', bottom:'5%', right:'20%' }] };
    }
    if (type === 'parallel') {
        var dims = [xF].concat(c.y_fields||[yF]);
        var pData = data.map(function(r){ return dims.map(function(d){ return r[d]||0; }); });
        return { parallelAxis: dims.map(function(d){ return { dim: dims.indexOf(d), name:d }; }),
            series:[{ type:'parallel', data: pData }] };
    }

    // 图表类型 → ECharts series type 映射
    function seriesType(t) {
        var m = { bar:'bar', line:'line', area:'line', stacked_bar:'bar', stacked_area:'line',
            combo:'bar', pictorial_bar:'pictorialBar', waterfall:'bar', boxplot:'boxplot',
            candlestick:'candlestick', theme_river:'themeRiver', graph:'graph', tree:'tree' };
        return m[t] || 'bar';
    }

    // 基础笛卡尔图表 + 所有未单独处理的类型
    var sType = seriesType(type);
    var isSmooth = (type==='line'||type==='area'||type==='theme_river');
    var isArea = (type==='area'||type==='theme_river');
    var isStacked = (type==='stacked_bar'||type==='stacked_area');

    var seriesArr = [];
    if (cF) {
        var groups = [];
        var gSeen = {};
        data.forEach(function(r) { var g = r[cF]||''; if (!gSeen[g]) { gSeen[g]=true; groups.push(g); } });
        groups.forEach(function(g) {
            var s = { name: g, type: sType,
                data: categories.map(function(cat) {
                    var row = data.find(function(r){ return (r[xF]||'')===cat && (r[cF]||'')===g; });
                    return row ? (row[yF]||0) : 0;
                }) };
            if (isSmooth) s.smooth = true;
            if (isArea) s.areaStyle = {};
            if (isStacked) s.stack = 'total';
            seriesArr.push(s);
        });
    } else {
        (c.y_fields||[yF]).forEach(function(f) {
            var s = { name: f, type: sType, data: seriesData(f) };
            if (isSmooth) s.smooth = true;
            if (isArea) s.areaStyle = {};
            if (isStacked) s.stack = 'total';
            seriesArr.push(s);
        });
    }

    var opt = base;
    opt.xAxis = { type:'category', data:categories, boundaryGap: sType!=='line' };
    opt.yAxis = { type:'value' };
    opt.series = seriesArr;
    return opt;
}

function renderKPI(c, el, data) {
    var v = (data && data.length) ? (data[0][(c.y_fields||[])[0]||''] || 0) : 0;
    var fmt = typeof v === 'number' ? v.toLocaleString() : v;
    el.innerHTML = '<div class="kpi"><div class="v">' + fmt + '</div><div class="l">' + (c.title||'') + '</div></div>';
}

function renderTable(c, el, data) {
    if (!data || !data.length) { el.innerHTML = '<div style="padding:20px;color:#999;">无数据</div>'; return; }
    var cols = Object.keys(data[0]);
    var h = '<div class="tbl"><table><thead><tr>';
    cols.forEach(function(k) { h += '<th>' + k + '</th>'; });
    h += '</tr></thead><tbody>';
    data.forEach(function(r) {
        h += '<tr>';
        cols.forEach(function(k) { h += '<td>' + (r[k]||'') + '</td>'; });
        h += '</tr>';
    });
    h += '</tbody></table></div>';
    el.innerHTML = h;
}

function onChartClick(chartId, params) {
    var c = (CONFIG.charts||[]).find(function(x){ return x.id===chartId; });
    if (!c || c.enable_cross_filter===false) return;
    var val = params.name || params.seriesName || '';
    var field = c.color_field || c.x_field || '';
    if (!field) return;
    if (!crossFilterState[field]) crossFilterState[field] = [];
    var idx = crossFilterState[field].indexOf(val);
    if (idx >= 0) { crossFilterState[field].splice(idx,1); if (!crossFilterState[field].length) delete crossFilterState[field]; }
    else crossFilterState[field].push(val);
    applyCrossFilter();
}

function applyCrossFilter() {
    var entries = Object.entries(crossFilterState).filter(function(e){ return e[1].length>0; });
    Object.entries(chartInstances).forEach(function(e){
        var id = e[0], inst = e[1];
        var c = (CONFIG.charts||[]).find(function(x){ return x.id===id; });
        if (!c || c.chart_type==='card'||c.chart_type==='table') return;
        var fd = (ALL_DATA[id]||[]).slice();
        entries.forEach(function(entry){ fd = fd.filter(function(r){ return entry[1].indexOf(r[entry[0]]||'') >= 0; }); });
        var opt = buildOption(c, fd);
        try { inst.setOption(opt, {notMerge:false}); } catch(e){}
    });
}

// ===== Bridge 函数 =====
function setEditMode(enabled) { document.body.classList.toggle('edit-mode', enabled); }
function selectChart(chartId) { var el = document.getElementById('chart-' + chartId); if (el) el.scrollIntoView({ behavior:'smooth', block:'center' }); }
function requestExportPNG() {}
function applyGlobalFilters(filtersJson) {}
function reloadConfig(configJson) { try { var cfg = JSON.parse(configJson); if (cfg) Object.assign(CONFIG, cfg); } catch(e){} }

window.setEditMode = setEditMode;
window.selectChart = selectChart;
window.toggleGridLines = function(show) {
    var grid = document.getElementById('grid');
    if (grid) { grid.classList.toggle('show-lines', show); }
};
window.requestExportPNG = requestExportPNG;
window.applyGlobalFilters = applyGlobalFilters;
window.reloadConfig = reloadConfig;

window.updateChartConfig = function(chartId, chartCfg) {
    var idx = (CONFIG.charts||[]).findIndex(function(c){ return c.id===chartId; });
    if (idx >= 0) { CONFIG.charts[idx] = chartCfg; }
    else { CONFIG.charts = CONFIG.charts || []; CONFIG.charts.push(chartCfg); }
    var card = document.getElementById('chart-' + chartId);
    if (card) {
        var hd = card.querySelector('.hd');
        if (hd) hd.textContent = chartCfg.title || '';
        // card/table: 直接注入预渲染 HTML
        var ct = chartCfg.chart_type || '';
        if ((ct === 'card' || ct === 'table') && chartCfg._prerendered_html) {
            var bd = card.querySelector('.bd');
            if (bd) bd.innerHTML = chartCfg._prerendered_html;
            return;
        }
    }
    var inst = chartInstances[chartId];
    if (inst && !inst.isDisposed()) {
        var data = ALL_DATA[chartId] || [];
        if (chartCfg._echarts_option) {
            try { inst.setOption(JSON.parse(chartCfg._echarts_option), {notMerge:true}); } catch(e){}
        } else {
            try { inst.setOption(buildOption(chartCfg, data), {notMerge:true}); } catch(e){}
        }
    }
};

window.refreshAllData = function(dataMap) {
    if (!dataMap) return;
    ALL_DATA = dataMap;
    crossFilterState = {};
    Object.entries(dataMap).forEach(function(e) {
        var id = e[0], data = e[1];
        var inst = chartInstances[id];
        if (inst && !inst.isDisposed()) {
            var c = (CONFIG.charts||[]).find(function(x){ return x.id===id; });
            if (c) {
                // 优先使用 Python 预渲染 option
                if (c._echarts_option) {
                    try { inst.setOption(eval('('+c._echarts_option+')'), {notMerge:true}); } catch(ex){}
                } else {
                    try { inst.setOption(buildOption(c, data), {notMerge:true}); } catch(ex){}
                }
            }
        }
    });
};

window.refreshChartData = function(chartId, data) {
    ALL_DATA[chartId] = data;
    var inst = chartInstances[chartId];
    if (inst) {
        var c = (CONFIG.charts||[]).find(function(x){ return x.id===chartId; });
        if (c) {
            if (c._echarts_option) {
                try { inst.setOption(eval('('+c._echarts_option+')'), {notMerge:true}); } catch(e){}
            } else {
                inst.setOption(buildOption(c, data), {notMerge:true});
            }
        }
    }
};

document.addEventListener('DOMContentLoaded', function() {
    try {
        if (window._INITIAL_DATA) { ALL_DATA = window._INITIAL_DATA; window._INITIAL_DATA = null; }
        initCharts();
        if (window.qt && window.qt.webChannelTransport) {
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.bridge = channel.objects.bridge;
                window.bridge.handle_js_action('page_ready', '{}');
            });
        }
    } catch(e) {
        var grid = document.getElementById('grid');
        if (grid) grid.innerHTML = '<div style="padding:40px;color:#FF4D4F;font-size:18px;text-align:center;">❌ 页面初始化失败<br><small>' + e.message + '</small></div>';
    }
});

window.addEventListener('resize', function() {
    Object.values(chartInstances).forEach(function(inst) {
        try { inst.resize(); } catch(e) {}
    });
});
</script>
</body>
</html>''')
    return ''.join(parts)
