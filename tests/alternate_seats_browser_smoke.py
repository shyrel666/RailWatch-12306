"""Offline native controls and full waitlist readback for each enabled seat."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from order_browser_smoke import OrderBrowserTests
from gui_12306_0 import TicketMonitor
from railwatch_alternate_options import NewTrainWindow
from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent, OrderJournal


# Independent expectations, checked against the public seatNameTrain mapping.
SEATS = {"二等座": ("ZE", "O"), "一等座": ("ZY", "M"), "硬座": ("YZ", "1"),
         "软座": ("RZ", "2"), "硬卧": ("YW", "3"), "软卧": ("RW", "4")}


class AlternateSeatsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OrderBrowserTests.setUpClass()
        cls.driver = OrderBrowserTests.driver
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})

    @classmethod
    def tearDownClass(cls):
        OrderBrowserTests.tearDownClass()

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def prepare(self, seat, seats=None):
        self.driver.get((ROOT / "tests/fixtures/multi-alternate.html").as_uri())
        self.page = OrderPage(self.driver, allow_fixture=True, poll_interval=.01, wait=lambda _: None)
        self.page.RESULT_UNKNOWN_TIMEOUT = .05
        self.page.RECOVERY_TAB_TIMEOUT = .05
        self.bound = []
        self.page.bind_intent = self.bound.append
        train = "G101" if seat in ("二等座", "一等座") else "K101"
        self.intent = OrderIntent("alternate", train, "2026-10-10", "北京", "上海", seat, ("张三",), "开车前1小时")
        self.config = {"date": self.intent.date, "date_range": "单日", "train_code": f"{train},{train[0]}102",
                       "from_station_cn": "北京", "to_station_cn": "上海", "passengers": "张三",
                       "auto_alternate": True, "alternate_mode": "multiple", "alternate_max_combinations": 6,
                       "seat_keyword": ",".join(seats or [seat]), "alternate_deadline": "开车前1小时"}
        self.js("""
          Object.assign(primary,{train:arguments[0],seat:arguments[1]});
          fixture.selected=[primary];fixture.draft=[primary];fixture.seats=arguments[2];fixture.trains=arguments[3];
          el('ticket_card_list').innerHTML=card(primary);
        """, train, seat, seats or [seat], self.config["train_code"].split(","))

    def submit(self, multiple=False):
        return self.page.alternate(self.driver.find_element("id", "candidate"), self.intent,
                                   plan_config=self.config if multiple else None)

    def test_each_seat_native_query_cell_submit_and_persisted_recovery(self):
        for seat, (prefix, _) in SEATS.items():
            with self.subTest(seat=seat), tempfile.TemporaryDirectory() as directory:
                self.prepare(seat)
                self.js("""
                  document.body.insertAdjacentHTML('beforeend','<table><tbody id=queryLeftTable></tbody></table>');
                  fixture.entryClicks=[];
                  el('queryLeftTable').innerHTML='<tr id=ticket_a><td>'+primary.train+'</td>'+arguments[0].map(prefix=>
                    '<td id='+prefix+'_a role=button hbdata=fixture hbid=fixture>候补</td>').join('')+'</tr>';
                  document.querySelectorAll('#queryLeftTable [role=button]').forEach(cell=>cell.setAttribute('onclick',
                    "fixture.entryClicks.push(this.id);document.getElementById('form').classList.remove('hidden')"));
                """, [value[0] for value in SEATS.values()])
                monitor = TicketMonitor(self.driver, self.config, log_callback=lambda _: None)
                monitor._row_snapshot = monitor.row_parser.snapshot_rows(monitor.target_seats)
                hit = monitor._find_hit_row()
                self.assertEqual((hit[0], hit[1], hit[-1]), (self.intent.train_code, seat, "alternate"))
                journal = OrderJournal(Path(directory) / "orders.sqlite3")
                journal.begin("seat-test", self.intent, self.config)
                self.page.mark = lambda stage, detail=None: journal.mark("seat-test", stage, self.intent.intent_id, detail)
                result = self.page.alternate(hit[4], self.intent)
                self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"), result.reason)
                journal.record(self.intent, result)
                self.assertEqual(self.js("return fixture.entryClicks"), [prefix + "_a"])
                restored = OrderJournal(journal.filename)
                saved = OrderIntent.from_dict(restored.pending()["intent"])
                self.assertEqual(saved.seat, seat)
                resumed = OrderPage(self.driver, allow_fixture=True).reconcile(saved, known_id="E123456")
                self.assertEqual(resumed.status, "pending_payment", resumed.reason)
                self.assertEqual(self.js("return fixture.submitClicks"), 1)

    def test_each_seat_recovery_and_fulfillment_require_exact_seat_and_bound_id(self):
        for seat in SEATS:
            with self.subTest(seat=seat):
                self.prepare(seat)
                for state, status in (("待兑现", "active"), ("兑现成功", "fulfilled")):
                    self.js("fixture.record(arguments[0])", state)
                    self.assertEqual(self.page.reconcile(self.intent, known_id="E123456").status, status)
                    self.assertEqual(self.page.result(self.intent).status, "unknown")
                    self.assertEqual(self.page.result(self.intent, known_id="E999999").status, "unknown")
                    # 高级软卧 must not match 软卧 through a substring.
                    wrong = "高级软卧" if seat == "软卧" else "二等座" if seat != "二等座" else "一等座"
                    self.js("document.querySelector('.order-item .ticket-info-txt span').textContent=arguments[0]", wrong)
                    self.assertEqual(self.page.result(self.intent, known_id="E123456").status, "unknown")
                self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_mixed_seat_plans_keep_configured_priority_and_exact_pairs(self):
        for seats in (["一等座", "二等座"], ["硬座", "软座", "硬卧", "软卧"]):
            with self.subTest(seats=seats), tempfile.TemporaryDirectory() as directory:
                self.prepare(seats[0], seats)
                journal = OrderJournal(Path(directory) / "orders.sqlite3")
                journal.begin("mixed", self.intent, self.config)
                self.page.bind_intent = journal.bind_alternatives
                self.page.mark = lambda stage, detail=None: journal.mark("mixed", stage, self.intent.intent_id, detail)
                self.js("fixture.collapsed=true")
                result = self.submit(multiple=True)
                self.assertEqual(result.status, "pending_payment", result.reason)
                saved = OrderIntent.from_dict(journal.pending()["intent"])
                expected = [(train, seat) for train in self.config["train_code"].split(",") for seat in seats][:6]
                self.assertEqual([(c.train_code, c.seat) for c in saved.choices], expected)
                journal.record(saved, result)
                self.assertEqual(OrderPage(self.driver, allow_fixture=True).reconcile(saved, known_id="E123456").status, "pending_payment")
                self.assertEqual(self.js("return fixture.submitClicks"), 1)

    def test_dated_editor_metadata_validates_every_enabled_seat_code(self):
        for seat in SEATS:
            with self.subTest(seat=seat):
                self.prepare(seat)
                self.js("""fixture.onRender=()=>document.querySelectorAll('.hbbtn').forEach(button=>{
                  const parts=button.dataset.info.split('#');parts.splice(10,0,fixture.date.replaceAll('-',''));button.dataset.info=parts.join('#');
                });""")
                result = self.submit(multiple=True)
                self.assertEqual(result.status, "pending_payment", result.reason)
                self.assertEqual(self.js("return fixture.selected.map(c=>c.seat)"), [seat, seat])
                self.assertEqual(self.js("return fixture.submitClicks"), 1)

    def test_wrong_missing_or_blank_editor_seat_code_never_adds_or_submits(self):
        for seat in SEATS:
            for mode in ("wrong", "missing", "blank"):
                with self.subTest(seat=seat, mode=mode):
                    self.prepare(seat)
                    self.js("""const mode=arguments[0],wrong=arguments[1];fixture.onRender=()=>{
                      document.querySelectorAll('.hbbtn').forEach(button=>{
                        if(mode==='missing')button.removeAttribute('data-info');
                        else {const parts=button.dataset.info.split('#');parts[4]=mode==='wrong'?wrong:'';button.dataset.info=parts.join('#');}
                      });
                    };""", mode, "M" if seat == "二等座" else "O")
                    result = self.submit(multiple=True)
                    self.assertEqual(result.status, "verification", result.reason)
                    self.assertIn("席别身份", result.reason)
                    self.assertEqual(self.js("return [fixture.adds.length,fixture.submitClicks]"), [0, 0])

    def test_unselected_unsupported_seats_are_skipped_and_selected_ones_block(self):
        for injected in (False, True):
            with self.subTest(injected=injected):
                self.prepare("一等座")
                self.js("fixture.seats.push('商务座','高级软卧','动卧')")
                if injected:
                    self.js("fixture.onAdd=()=>fixture.draft.push({...primary,seat:'商务座'})")
                result = self.submit(multiple=True)
                self.assertEqual(result.status, "verification" if injected else "pending_payment", result.reason)
                self.assertTrue(all(item["seat"] == "一等座" for item in self.js("return fixture.adds")))
                self.assertEqual(self.js("return fixture.submitClicks"), 0 if injected else 1)

    def test_changed_primary_seat_or_standing_setting_never_submits(self):
        for seat in SEATS:
            for field in ("seat", "standing"):
                with self.subTest(seat=seat, field=field):
                    self.prepare(seat)
                    self.js("""if(arguments[0]==='standing')el('is_open').textContent='已开启';
                      else document.querySelector('#ticket_card_list .ticket-info-txt span').textContent=arguments[1];
                    """, field, "二等座" if seat != "二等座" else "一等座")
                    self.assertEqual(self.submit().status, "verification")
                    self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_new_train_conditions_and_fulfillment_keep_each_saved_seat(self):
        for seat in SEATS:
            with self.subTest(seat=seat):
                self.prepare(seat)
                self.js((ROOT / "tests/fixtures/new-train-controls.js").read_text(encoding="utf-8"))
                self.js("fixture.ruleSeat=arguments[0]", seat)
                self.intent = replace(self.intent, new_train_windows=(NewTrainWindow(self.intent.date, 8, 22),))
                result = self.submit()
                self.assertEqual(result.status, "pending_payment", result.reason)
                self.js("""fixture.record('兑现成功',[{...primary,train:primary.train[0]+'999',from:'北京南',to:'上海虹桥'}]);
                  document.querySelector('.order-item .ticket-card').classList.add('success');
                  document.querySelector('.order-item .ticket-station-start').insertAdjacentHTML('beforeend','<div class=ticket-station-time>09:30</div>');
                  document.querySelector('.order-item').insertAdjacentHTML('beforeend','<div class=success-temporary-train>临客 兑现成功</div>');
                """)
                result = self.page.reconcile(self.intent, known_id="E123456")
                self.assertEqual(result.status, "fulfilled", result.reason)
                self.js("document.querySelector('.order-item .ticket-info-txt span').textContent=arguments[0]",
                        "高级软卧" if seat == "软卧" else "二等座" if seat != "二等座" else "一等座")
                self.assertEqual(self.page.reconcile(self.intent, known_id="E123456").status, "unknown")
                self.assertEqual(self.js("return fixture.submitClicks"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2, defaultTest="AlternateSeatsBrowserTests")
