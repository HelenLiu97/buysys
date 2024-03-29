import datetime
import json
import logging
import os
import xlrd
from tools_me.other_tools import customer_required, save_file, excel_to_data, asin_num, sum_code, xianzai_time, \
    date_to_week, transferContent, now_day, verify_login_time
from tools_me.parameter import RET, MSG, TASK_DIR, PHOTO_DIR
from . import customer_blueprint
from flask import render_template, request, jsonify, session, g
from tools_me.mysql_tools import SqlData


@customer_blueprint.route('/un_lock/', methods=['GET', 'POST'])
@customer_required
def order_un_lock():
    if request.method == 'GET':
        data = request.args.get('data')
        context = dict()
        context['task_code'] = data
        return render_template('customer/un_lock.html', **context)
    if request.method == 'POST':
        try:
            data = json.loads(request.form.get('data'))
            run_time = request.form.get('run_time')
            task_code_str = data.get('task_code')
            task_code_list = task_code_str.split(',')
            for i in task_code_list:
                SqlData().update_order_one_field('task_run_time', run_time, i)
                SqlData().update_order_one_int('lock', 0, i)
            return jsonify({'code': RET.OK, 'msg': MSG.OK})
        except Exception as e:
            logging.error(e)
            return jsonify({'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR})


@customer_blueprint.route('/order_lock/', methods=['POST'])
@customer_required
def order_lock():
    try:
        data = json.loads(request.form.get('data'))
        for i in data:
            task_stats = i.get('task_stats')
            if task_stats == '待留评' or task_stats == '已分配':
                return jsonify({'code': RET.SERVERERROR, 'msg': '订单中包含已完成或待留评订单!'})
        for n in data:
            task_code = n.get('task_code').strip()
            SqlData().update_order_one_int('lock', 1, task_code)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})
    except Exception as e:
        logging.error(str(e))
        return jsonify({'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR})


@customer_blueprint.route('/del_task', methods=['GET'])
@customer_required
def del_task():
    sum_order_code = request.args.get('sum_order_code')
    user_id = g.cus_user_id
    results = {'code': RET.OK, 'msg': MSG.OK}
    task_state = SqlData().search_task_one_field('pay_cus', sum_order_code)
    if task_state == '已支付':
        results['code'] = RET.SERVERERROR
        results['msg'] = '订单已确认!不可取消请刷新当前界面!'
        return jsonify(results)
    if sum_order_code:
        try:
            SqlData().del_task(sum_order_code, user_id)
            return jsonify(results)
        except Exception as e:
            logging.error(str(e))
            results['code'] = RET.SERVERERROR
            results['msg'] = MSG.DATAERROR
            return jsonify(results)


@customer_blueprint.route('/preview_money', methods=['GET'])
@customer_required
def preview_money():
    cus_id = g.cus_id
    user_id = g.cus_user_id
    task_json = SqlData().search_cus_field('task_json', cus_id)
    if not task_json:
        return '请先导入表格文件!'
    task_dict = json.loads(task_json, strict=False)
    serve_money = task_dict.get('serve_money')
    good_sum_money = task_dict.get('good_sum_money')
    terrace = task_dict.get('terrace')
    sum_num = task_dict.get('sum_num')
    serve_dis = "%.2f" % serve_money
    exchange = SqlData().search_user_field('dollar_exchange', user_id)
    good_dis = "%.2f" % (good_sum_money * float(exchange))
    sum_money = float(serve_dis) + float(good_dis)
    context = dict()
    context['serve_money'] = str(serve_dis) + " = " + str(serve_money) + "(服务费总额)"
    context['good_money'] = str(good_dis) + " = " + str(round(good_sum_money, 2)) + "(商品金额总额)" + "*" + str(float(exchange)) + "(汇率)"
    context['sum_money'] = str(round(sum_money, 2))
    context['terrace'] = terrace
    context['sum_num'] = sum_num
    return render_template('customer/preview_money.html', **context)


@customer_blueprint.route('/again_preview', methods=['GET', 'POST'])
@customer_required
def again_preview():
    if request.method == 'GET':
        user_id = g.cus_user_id
        cus_id = g.cus_id
        dome_task = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(dome_task)
        task_list = task_dict.get('task_info')

        # 订单数据量
        sum_menber = len(task_list)

        # 检查订单时间:
        run_time_list = list()
        index = 1
        for i in task_list:
            task_run_time = i.get('task_run_time')
            t1 = now_day() + ' 00:00:00'
            if verify_login_time(task_run_time, t1):
                run_time_list.append(index)
            index += 1
        if len(run_time_list) > 0:
            s = ''
            for num in run_time_list:
                dome = str(num) + "行, "
                s += dome
            s = '请修改第: ' + s + '下单时间!(不得小于当天日期....)'
            return jsonify({'code': RET.SERVERERROR, 'msg': s})

        # 取出asin, serve_class, good_money 列表
        asin_list = list()
        serve_class_list = list()
        good_money_list = list()
        for i in task_list:
            asin_list.append(i.get('asin'))
            serve_class_list.append(i.get('serve_class'))
            good_money_list.append(i.get('good_money'))

        # 计算商品总额
        good_sum_money = 0
        for i in good_money_list:
            good_sum_money += float(i)

        # 获取每个asin对饮的数量(字典)
        asin_num_dict = asin_num(asin_list)
        # 去重后的asin列表
        one_asin_list = list(asin_num_dict.keys())
        # 将asin和serve_class组合为列表,数据结构:[['1AJFOAFJA', 'Review/FeedBack'], ['AB', 'FeedBack']]
        asin_group = list()
        index = 0
        for i in asin_list:
            one_asin = [asin_list[index], serve_class_list[index]]
            asin_group.append(one_asin)
            index += 1

        # 计算review的数量和feedback数量
        asin_detail_list = list()
        for asin in one_asin_list:
            asin_detail = dict()
            review_num = 0
            feedback_num = 0
            for i in asin_group:
                if i[0] == asin and i[1] == "Review":
                    review_num += 1
                if i[0] == asin and i[1] == "FeedBack":
                    feedback_num += 1
                if i[0] == asin and i[1] == "Review/FeedBack":
                    review_num += 1
                    feedback_num += 1
            asin_detail['asin'] = asin
            num = asin_num_dict.get(asin)
            asin_detail['num'] = num
            asin_detail['review_num'] = review_num
            asin_detail['feedback'] = feedback_num
            asin_detail['bili'] = review_num / num
            asin_detail_list.append(asin_detail)

        # 查询服务商的收费标准
        serve_json = SqlData().search_cus_field('amz_money', cus_id)
        if not serve_json:
            return jsonify({'code': RET.SERVERERROR, 'msg': "请联系服务商设置收费标准!"})
        else:
            serve_dict = json.loads(serve_json)
            feedback = serve_dict.get('feedback')
            if not feedback:
                return jsonify({'code': RET.SERVERERROR, 'msg': "请联系服务商设置FeedBack收费标准!"})

        # 判断留评比例是否符合要求
        pass_asin = list()
        for i in asin_detail_list:
            bili = i.get('bili')
            bili_baifen = str(int(bili * 100))
            if bili_baifen in serve_dict:
                i['review_price'] = serve_dict.get(str(bili_baifen))
            else:
                pass_asin.append(i)
        if len(pass_asin) > 0:
            s = "以下ASIN的留评比例不符合服务商的收费标准: "
            for i in pass_asin:
                asin = i.get('asin')
                bili = str(int(i.get('bili') * 100)) + '%'
                s1 = asin + ": " + bili + "。 "
                s += s1
            s + '更多收费标准请咨询服务商!'
            return jsonify({'code': RET.SERVERERROR, 'msg': s})

        for i in asin_detail_list:
            asin_n = i.get('num')
            price = i.get('review_price')
            review_money = asin_n * price
            feedback_num = i.get('feedback')
            feedback_money = feedback_num * feedback
            i['sum_money'] = review_money + feedback_money

        serve_money = 0
        for i in asin_detail_list:
            money = i.get('sum_money')
            serve_money += money
        task_dict['serve_money'] = serve_money

        task_dict['good_sum_money'] = good_sum_money

        task_dict['sum_num'] = sum_menber
        # print(task_info_dict)
        task_info_json = json.dumps(task_dict, ensure_ascii=False)
        string = transferContent(task_info_json)
        label = g.cus_label
        SqlData().update_user_cus('task_json', string, user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})


@customer_blueprint.route('/once_again', methods=['GET', 'POST'])
@customer_required
def once_again():
    if request.method == 'POST':
        cus_id = g.cus_id
        task_code = request.args.get('task_code')
        dome_task = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(dome_task)
        task_list = task_dict.get('task_info')
        s = None
        for q in task_list:
            task_code_key = q.get('task_code')
            if task_code == task_code_key:

                s = q.copy()
        t = sum_code()
        s['task_code'] = t
        task_list.append(s)
        task_json = json.dumps(task_dict, ensure_ascii=False)
        user_id = g.cus_user_id
        label = g.cus_label
        task_json = transferContent(task_json)
        SqlData().update_user_cus('task_json', task_json, user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})
    if request.method == 'GET':
        cus_id = g.cus_id
        task_code = request.args.get('task_code')
        dome_task = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(dome_task)
        task_list = task_dict.get('task_info')
        for i in task_list:
            if task_code == i.get('task_code'):
                task_list.remove(i)
        task_json = json.dumps(task_dict, ensure_ascii=False)
        user_id = g.cus_user_id
        label = g.cus_label
        task_json = transferContent(task_json)
        SqlData().update_user_cus('task_json', task_json, user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})


@customer_blueprint.route('/again_edit', methods=['GET', 'POST'])
@customer_required
def again_edit():
    if request.method == 'GET':
        task_code = request.args.get('task_code')
        context = dict()
        context['task_code'] = task_code
        return render_template('customer/again_edit.html', **context)
    if request.method == 'POST':
        try:
            data = json.loads(request.form.get('data'))
            task_code = data.get('task_code')
            run_time = data.get('sum_time')
            asin = data.get('asin')
            store_name = data.get('store_name')
            key_word = data.get('key_word')
            kw_location = data.get('kw_location')
            good_name = data.get('good_name')
            good_money = data.get('good_money')
            good_link = data.get('good_link')
            pay_method = data.get('pay_method')
            serve_class = data.get('serve_class')
            mail_method = data.get('mail_method')
            note = data.get('note')
            cus_id = g.cus_id
            dome_task = SqlData().search_cus_field('task_json', cus_id)
            task_dict = json.loads(dome_task)
            task_list = task_dict.get('task_info')
            for i in task_list:
                if task_code == i.get('task_code'):
                    if run_time:
                        i['task_run_time'] = run_time
                    if asin:
                        i['asin'] = asin
                    if store_name:
                        i['store_name'] = store_name
                    if key_word:
                        i['key_word'] = key_word
                    if kw_location:
                        i['kw_location'] = kw_location
                    if good_money:
                        i['good_money'] = good_money
                    if good_name:
                        i['good_name'] = good_name
                    if good_link:
                        i['good_link'] = good_link
                    if pay_method:
                        i['pay_method'] = pay_method
                    i['serve_class'] = serve_class
                    if mail_method:
                        i['mail_method'] = mail_method
                    if note:
                        i['note'] = note
            task_json = json.dumps(task_dict, ensure_ascii=False)
            user_id = g.cus_user_id
            label = g.cus_label
            task_json = transferContent(task_json)
            SqlData().update_user_cus('task_json', task_json, user_id, label)
            return jsonify({'code': RET.OK, 'msg': MSG.OK})
        except Exception as e:
            logging.error(str(e))
            return jsonify({'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR})


@customer_blueprint.route('/task_again/', methods=['GET'])
@customer_required
def task_again():
    sum_order_code = request.args.get('sum_order_code')
    results = {"code": RET.OK, "msg": MSG.OK, "count": 0, "data": ""}
    try:
        cus_id = g.cus_id
        user_id = g.cus_user_id
        dome_task = SqlData().search_cus_field('task_json', cus_id)
        if not dome_task:
            task_info = SqlData().search_task_detail(sum_order_code)
            terrace = SqlData().search_user_field('terrace', user_id)
            task_dict = dict()
            task_dict['terrace'] = terrace
            task_dict['serve_money'] = 0
            task_dict['good_sum_money'] = 0
            task_dict['sum_num'] = 0
            task_dict['task_info'] = task_info
            task_json = json.dumps(task_dict, ensure_ascii=False)
            label = g.cus_label
            user_id = g.cus_user_id
            task_json = transferContent(task_json)
            SqlData().update_user_cus('task_json', task_json, user_id, label)
            results['data'] = task_info
            results['count'] = len(task_info)
        else:
            task_dict = json.loads(dome_task)
            task_info = task_dict.get('task_info')
            results['data'] = task_info
            results['count'] = len(task_info)
    except Exception as e:
        logging.warning('没有符合条件的数据' + str(e))
        results['code'] = RET.SERVERERROR
        results['msg'] = MSG.NODATA
    return results


@customer_blueprint.route('/amz_search/', methods=['GET'])
@customer_required
def search_html():
    if request.method == 'GET':
        user_id = g.cus_user_id
        terrace = SqlData().search_user_field('terrace', user_id)
        field = request.args.get('field')
        value = request.args.get('value')
        if not all([field, value]):
            return "请填写参数后搜索"
        context = dict()
        context['field'] = field
        context['value'] = value
        context['terrace'] = terrace
        return render_template('customer/search.html', **context)


@customer_blueprint.route('/urgent', methods=['GET'])
@customer_required
def urgent_review():
    if request.method == 'GET':
        task_code = request.args.get('task_code')
        # terrace = request.args.get('terrace')
        try:
            task_state = SqlData().search_order_one('task_state', task_code)
            urgent = SqlData().search_order_one('urgent', task_code)
            if task_state != "待留评":
                return jsonify({'code': RET.SERVERERROR, 'msg': '该订单不是待留评订单不可催评!'})

            if urgent:
                return jsonify({'code': RET.SERVERERROR, 'msg': '已催屏,不可重复催屏!'})

            now_time = xianzai_time()
            SqlData().update_review_one('urgent', now_time, task_code)
            return jsonify({'code': RET.OK, 'msg': MSG.OK})
        except Exception as e:
            logging.error(str(e))
            return jsonify({'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR})


@customer_blueprint.route('/up_review_pic', methods=['POST'])
@customer_required
def up_review_pic():
    user_id = g.cus_user_id
    results = {'code': RET.OK, 'msg': MSG.OK}
    file = request.files.get('file')
    task_code = request.args.get('task_code')
    image_state = SqlData().search_order_one('review_info', task_code)
    if not image_state:
        return jsonify({'code': RET.SERVERERROR, 'msg': '此订单不支持上传图片'})
    file_name = str(user_id) + "-" + sum_code() + ".PNG"
    file_path = PHOTO_DIR + "/" + file_name
    file.save(file_path)
    static_path = '/static/photo/' + file_name
    file_path = 'http://114.116.236.27:8080/user/pic_link?path=' + static_path
    if image_state == 'T':
        phone_link = dict()
        phone_link[file_path] = 1
        link_json = json.dumps(phone_link, ensure_ascii=False)
        SqlData().update_review_one('review_info', link_json, task_code)
    else:
        phone_link = json.loads(image_state)
        if len(phone_link) == 4:
            return jsonify({'code': RET.SERVERERROR, 'msg': '最多可上传四张图片'})
        phone_link[file_path] = 1
        link_json = json.dumps(phone_link, ensure_ascii=False)
        SqlData().update_review_one('review_info', link_json, task_code)
    return jsonify(results)


@customer_blueprint.route('/edit_smt', methods=['GET', 'POST'])
@customer_required
def edit_smt():
    if request.method == 'GET':
        task_code = request.args.get('task_code')
        context = {'task_code': task_code}
        return render_template('customer/smt_review.html', **context)
    if request.method == 'POST':
        try:
            data = json.loads(request.form.get('data'))
            task_code = request.args.get('task_code')
            review_title = data.get('review_title')
            title_state = SqlData().search_order_one('review_title', task_code)
            if title_state != "T":
                return jsonify({'code': RET.SERVERERROR, 'msg': '此订单不可添加文字留评'})
            if review_title:
                SqlData().update_review_one('review_title', review_title, task_code)
            results = {'code': RET.OK, 'msg': MSG.OK}
            return jsonify(results)
        except Exception as e:
            logging.error(str(e))
            results = {'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR}
            return jsonify(results)


@customer_blueprint.route('/edit_review', methods=['GET', 'POST'])
@customer_required
def edit_review():
    if request.method == 'GET':
        return render_template('customer/edit_review.html')
    if request.method == 'POST':
        try:
            data = json.loads(request.form.get('data'))
            task_code = data.get('task_code').strip()
            review_title = data.get('review_title')
            review_info = data.get('review_info')
            feedback_info = data.get('feedback_info')
            serve = SqlData().search_order_one('serve_class', task_code)
            if review_title:
                if 'REVIEW' in serve.upper():
                    review_title = transferContent(review_title)
                    SqlData().update_review_one('review_title', review_title, task_code)
                else:
                    results = {'code': RET.SERVERERROR, 'msg': '次订单没有编辑评论信息权限!'}
                    return jsonify(results)
            if review_info:
                if 'REVIEW' in serve.upper():
                    review_info = transferContent(review_info)
                    SqlData().update_review_one('review_info', review_info, task_code)
                else:
                    results = {'code': RET.SERVERERROR, 'msg': '次订单没有编辑评论信息权限!'}
                    return jsonify(results)
            if feedback_info:
                if 'FEEDBACK' in serve.upper():
                    feedback_info = transferContent(feedback_info)
                    SqlData().update_review_one('feedback_info', feedback_info, task_code)
                else:
                    results = {'code': RET.SERVERERROR, 'msg': '次订单没有编辑Feedback信息权限!'}
                    return jsonify(results)
            results = {'code': RET.OK, 'msg': MSG.OK}
            return jsonify(results)
        except Exception as e:
            print(e)
            logging.error(str(e))
            results = {'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR}
            return jsonify(results)


@customer_blueprint.route('/edit_sum', methods=['GET', 'POST'])
@customer_required
def edit_sum():
    if request.method == 'GET':
        sum_order_code = request.args.get('sum_order_code')
        user_id = g.cus_user_id
        terrace = SqlData().search_user_field('terrace', user_id)
        pay_photo = ""
        if terrace == 'AMZ':
            pay_photo = SqlData().search_user_field('amz_serve', user_id)
        if terrace == 'SMT':
            pay_photo = SqlData().search_user_field('note', user_id)
        if not pay_photo:
            # 空白图片链接
            pay_photo = 'https://i.loli.net/2019/08/29/m5TuFrJAo3vDBCt.png'

        context = {'sum_order_code': sum_order_code,
                   'pay_photo': pay_photo}
        return render_template('customer/sub_pay.html', **context)
    if request.method == 'POST':
        data = json.loads(request.form.get('data'))
        sum_order_code = data.get('sum_order_code')
        note = data.get('note')
        if note:
            SqlData().update_task_one('note', note, sum_order_code)
        results = {'code': RET.OK, 'msg': MSG.OK}
        return jsonify(results)


@customer_blueprint.route('/up_pay_pic', methods=['POST'])
@customer_required
def up_pay_pic():
    user_id = g.cus_user_id
    results = {'code': RET.OK, 'msg': MSG.OK}
    file = request.files.get('file')
    sum_order_code = request.args.get('sum_order_code')
    file_name = str(user_id) + "-" + sum_order_code + ".PNG"
    file_path = PHOTO_DIR + "/" + file_name
    file.save(file_path)
    static_path = '/static/photo/' + file_name
    file_path = 'http://114.116.236.27:8080/user/pic_link?path=' + static_path
    SqlData().update_task_one('deal_num', file_path, sum_order_code)
    return jsonify(results)
    # filename = sm_photo(file_path)
    # if filename == 'F':
    #     os.remove(file_path)
    #     return jsonify({'code': RET.SERVERERROR, 'msg': '不可上传相同图片,请重新上传!'})
    # if filename:
    #     os.remove(file_path)

    # else:
    #     return jsonify({'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR})


@customer_blueprint.route('/task_choose', methods=['GET', 'POST'])
@customer_required
def task_choose():
    user_id = g.cus_user_id
    label = g.cus_label
    cus_id = g.cus_id
    if request.method == 'GET':
        SqlData().update_user_cus('task_json', '', user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})

    if request.method == 'POST':
        task_json = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(task_json, strict=False)

        task_list = task_dict.get('task_info')
        serve_money = task_dict.get('serve_money')
        good_sum_money = task_dict.get('good_sum_money')
        terrace = task_dict.get('terrace')
        sum_num = task_dict.get('sum_num')
        serve_dis = "%.2f" % serve_money
        exchange = SqlData().search_user_field('dollar_exchange', user_id)
        good_dis = "%.2f" % (good_sum_money * float(exchange))
        sum_money = round(float(serve_dis) + float(good_dis), 2)

        sum_order_code = sum_code()
        parent_id = SqlData().insert_task_parent(user_id, sum_order_code)

        SqlData().update_task_one('terrace', terrace, sum_order_code)
        SqlData().update_task_one('sum_num', sum_num, sum_order_code)
        SqlData().update_task_one('serve_money', float(serve_dis), sum_order_code)
        SqlData().update_task_one('good_money', float(good_dis), sum_order_code)
        SqlData().update_task_one('sum_money', sum_money, sum_order_code)
        now_time = xianzai_time()
        SqlData().update_task_one('sum_time', now_time, sum_order_code)
        label = g.cus_label
        SqlData().update_task_one('customer_label', label, sum_order_code)

        index = 1
        for i in task_list:
            task_code = sum_order_code + '-' + str(index)
            if isinstance(i, list):
                country = i[0]
                task_run_time = i[1]
                asin = i[2]
                key_word = i[3]
                kw_location = i[4]
                store_name = i[5]
                good_name = i[6]
                good_money = i[7]
                good_link = i[8]
                pay_method = i[9]
                serve_class = i[10]
                mail_method = i[11]
                note = i[12]
                review_title = i[13]
                review_info = i[14]
                feedback_info = i[15]
            else:
                country = i.get('country')
                task_run_time = i.get('task_run_time')
                asin = i.get('asin')
                key_word = i.get('key_word')
                kw_location = i.get('kw_location')
                store_name = i.get('store_name')
                good_name = i.get('good_name')
                good_money = i.get('good_money')
                good_link = i.get('good_link')
                pay_method = i.get('pay_method')
                serve_class = i.get('serve_class')
                mail_method = i.get('mail_method')
                note = i.get('note')
                review_title = ''
                review_info = ''
                feedback_info = ''
            try:
                SqlData().insert_task_detail(parent_id, task_code, country, asin, key_word, kw_location, store_name,
                                             good_name, good_money, good_link, pay_method, task_run_time, serve_class,
                                             mail_method, note, review_title, review_info, feedback_info, user_id)
                index += 1
            except Exception as e:
                logging.error(str(e))
                return jsonify({'code': RET.SERVERERROR, 'msg': '上传失败!'})
        SqlData().update_user_cus('task_json', '', user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})


@customer_blueprint.route('/preview_index', methods=['GET'])
@customer_required
def preview_index():
    cus_id = g.cus_id
    user_id = g.cus_user_id
    task_json = SqlData().search_cus_field('task_json', cus_id)
    if not task_json:
        return '请先导入表格文件!'
    task_dict = json.loads(task_json, strict=False)
    serve_money = task_dict.get('serve_money')
    good_sum_money = task_dict.get('good_sum_money')
    terrace = task_dict.get('terrace')
    sum_num = task_dict.get('sum_num')
    serve_dis = "%.2f" % serve_money
    exchange = SqlData().search_user_field('dollar_exchange', user_id)
    good_dis = "%.2f" % (good_sum_money * float(exchange))
    sum_money = float(serve_dis) + float(good_dis)
    context = dict()
    context['serve_money'] = str(serve_dis) + " = " + str(serve_money) + "(服务费总额)"
    context['good_money'] = str(good_dis) + " = " + str(round(good_sum_money, 2)) + "(商品金额总额)" + "*" + str(float(exchange)) + "(汇率)"
    context['sum_money'] = str(round(sum_money, 2))
    context['terrace'] = terrace
    context['sum_num'] = sum_num
    return render_template('customer/preview_task.html', **context)


@customer_blueprint.route('/smt_choose', methods=['GET', 'POST'])
@customer_required
def smt_choose():
    user_id = g.cus_user_id
    label = g.cus_label
    cus_id = g.cus_id
    if request.method == 'GET':
        SqlData().update_user_cus('task_json', '', user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})

    if request.method == 'POST':
        task_json = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(task_json, strict=False)
        task_list = task_dict.get('task_info')
        serve_money = float(task_dict.get('serve_money')) + float(task_dict.get('other_money'))
        good_sum_money = task_dict.get('good_money')
        terrace = task_dict.get('terrace')
        sum_num = task_dict.get('sum_num')
        sum_money = float(task_dict.get('sum_money'))
        pay_method = task_dict.get('pay_method')
        buy_method = task_dict.get('buy_method')
        sum_order_code = sum_code()
        parent_id = SqlData().insert_task_parent(user_id, sum_order_code)
        SqlData().update_task_one('terrace', terrace, sum_order_code)
        SqlData().update_task_one('sum_num', sum_num, sum_order_code)
        SqlData().update_task_one('serve_money', serve_money, sum_order_code)
        SqlData().update_task_one('good_money', good_sum_money, sum_order_code)
        SqlData().update_task_one('sum_money', sum_money, sum_order_code)
        now_time = xianzai_time()
        SqlData().update_task_one('sum_time', now_time, sum_order_code)
        label = g.cus_label
        SqlData().update_task_one('customer_label', label, sum_order_code)
        SqlData().update_task_one('pay_middle', buy_method, sum_order_code)

        index = 1
        for i in task_list:
            task_code = sum_order_code + '-' + str(index)
            country = i[1]
            task_run_time = i[0]
            store_name = i[2]
            key_word = i[3]
            asin = i[4]
            good_search_money = i[5]
            good_link = i[6]
            mail_method = i[7]
            sku = i[8]
            good_money = i[9]
            mail_money = i[10]
            text_review = i[11]
            image_review = i[12]
            if len(i) == 14:
                default_review = i[13]
            else:
                default_review = ''
            note = ""

            # good_search_money=AMZ.good_name, sku=AMZ.kw_location, mail_money=AMZ.serve_class, text_review=AMZ.review_
            # title, image_review=AMZ.review_info, default_review=AMZ.feedback_info

            try:
                SqlData().insert_task_detail(parent_id, task_code, country, asin, key_word, sku, store_name,
                                             good_search_money, good_money, good_link, pay_method, task_run_time, mail_money,
                                             mail_method, note, text_review, image_review, default_review, user_id)
                index += 1
            except Exception as e:
                logging.error(str(e))
                return jsonify({'code': RET.SERVERERROR, 'msg': '上传失败!'})
        SqlData().update_user_cus('task_json', '', user_id, label)
        return jsonify({'code': RET.OK, 'msg': MSG.OK})


@customer_blueprint.route('/smt_preview', methods=['GET'])
@customer_required
def smt_preview():
    if request.method == 'GET':
        try:
            cus_id = g.cus_id
            user_id = g.cus_user_id
            label = g.cus_label
            method = request.args.get('method')
            pay_method = request.args.get('pay_method')
            bili = request.args.get('bili')
            task_json = SqlData().search_cus_field('task_json', cus_id)
            if not task_json:
                return '请先导入表格文件!'
            task_dict = json.loads(task_json, strict=False)
            task_info = task_dict.get('task_info')
            sum_num = task_dict.get('sum_num')
            terrace = task_dict.get('terrace')
            good_sum_money = task_dict.get('good_sum_money')
            mail_sum_money = task_dict.get('mail_sum_money')
            text_num = task_dict.get('text_num')
            image_num = task_dict.get('image_num')
            sunday_num = task_dict.get('sunday_num')

            if pay_method == "默认":
                exchange_dis = SqlData().search_cus_field('exchange_dis', cus_id)
            else:
                pay_dis = SqlData().search_user_field('pay_discount', user_id)
                pay_dict = json.loads(pay_dis)
                exchange_dis = pay_dict.get(pay_method)

            exchange = SqlData().search_user_field('dollar_exchange', user_id)

            smt_serve = SqlData().search_cus_one_field('amz_money', user_id, label)
            smt_dict = json.loads(smt_serve)
            _bili = int(bili)
            bili = _bili / 100
            default = round(sum_num * bili)
            for i in task_info[:default]:
                i.append('T')
            task_dict['task_info'] = task_info
            SqlData().update_user_cus('task_json', task_info, user_id, label)

            smt_dict = smt_dict.get(str(_bili))
            pc_money = smt_dict.get('pc_money')
            app_money = smt_dict.get('app_money')
            text_money = smt_dict.get('text_money')
            image_money = smt_dict.get('image_money')
            sunday_money = smt_dict.get('sunday_money')
            if not all([pc_money, app_money, text_money, image_money, sunday_money]):
                return '请联系服务商完善收费标准!'
            good_sum_money = float("%.3f" % good_sum_money)
            mail_sum_money = float("%.3f" % mail_sum_money)
            s = (good_sum_money + mail_sum_money) * exchange * exchange_dis
            if method == 'PC':
                q = sum_num * float(pc_money)
            else:
                # APP
                q = sum_num * float(app_money)
            text = text_num * float(text_money)
            image = image_num * float(image_money)
            sunday = sunday_num * float(sunday_money)
            other_money = text + image + sunday
            context = dict()
            context['serve_money'] = str(q) + " = 服务费总额"
            context['good_money'] = str(round(s, 2)) + " = (商品金额总额 + 邮费总额) * 汇率  * 折扣"
            context['other_money'] = str(other_money) + "=文字留评) +图片留评 +周日留评"
            context['sum_money'] = "%.2f" % (q + s + other_money)
            context['sum_num'] = sum_num
            context['terrace'] = terrace
            task_dict['sum_money'] = "%.2f" % (q + s + other_money)
            task_dict['serve_money'] = str(q)
            task_dict['good_money'] = str(s)
            task_dict['other_money'] = str(other_money)
            task_dict['pay_method'] = pay_method
            task_dict['buy_method'] = method
            task_json = json.dumps(task_dict, ensure_ascii=False)
            task_json = transferContent(task_json)
            SqlData().update_user_cus('task_json', task_json, user_id, label)
            return render_template('customer/smt_preview_task.html', **context)
        except Exception as e:
            logging.error(str(e))
            return jsonify({'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR})


@customer_blueprint.route('/smt_up_preview', methods=['GET', 'POST'])
@customer_required
def smt_up_preview():
    cus_id = g.cus_id
    results = {'code': RET.OK, 'msg': MSG.OK}
    if request.method == 'GET':
        limit = request.args.get('limit')
        page = request.args.get('page')
        task_json = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(task_json, strict=False)
        task_list = task_dict.get('task_info')
        data = list()
        for i in task_list:
            one_dict = dict()
            one_dict['task_run_time'] = i[1]
            one_dict['country'] = i[0]
            one_dict['store_name'] = i[2]
            one_dict['key_word'] = i[3]
            one_dict['asin'] = i[4]
            one_dict['good_search_money'] = i[5]
            one_dict['good_link'] = i[6]
            one_dict['mail_method'] = i[7]
            one_dict['sku'] = i[8]
            one_dict['good_money'] = i[9]
            one_dict['mail_money'] = i[10]
            one_dict['text_review'] = i[11]
            one_dict['image_review'] = i[12]
            if len(i) == 14:
                one_dict['default_review'] = i[13]
            else:
                one_dict['default_review'] = ''
            data.append(one_dict)
        page_list = list()
        for i in range(0, len(data), int(limit)):
            page_list.append(data[i:i + int(limit)])
        results['data'] = page_list[int(page) - 1]
        results['count'] = len(data)
        return results


@customer_blueprint.route('/smt_task', methods=['GET', 'POST'])
@customer_required
def smt_task():
    user_id = g.cus_user_id
    terrace = SqlData().search_user_field('terrace', user_id)
    if terrace != 'SMT':
        return '此账号没有查看权限!!!'
    if request.method == 'GET':
        user_id = g.cus_user_id
        label = g.cus_label
        pay_dis = SqlData().search_user_field('pay_discount', user_id)
        smt_serve = SqlData().search_cus_one_field('amz_money', user_id, label)
        context = dict()
        if not pay_dis:
            context['pay_list'] = []
        if pay_dis:
            pay_dict = json.loads(pay_dis)
            context['pay_list'] = list(pay_dict.keys())

        if not smt_serve:
            context['bili_list'] = []

        if smt_serve:
            smt_dict = json.loads(smt_serve)
            bili_list = list(smt_dict.keys())
            context['bili_list'] = bili_list
        return render_template('customer/cus_smt_task.html', **context)

    # 预存表格数据到task_json字段中
    if request.method == 'POST':
        file = request.files.get('file')
        filename = file.filename
        file_path = save_file(file, filename, TASK_DIR)
        results = {'code': RET.OK, 'data': MSG.OK}
        user_id = g.cus_user_id
        try:
            if 'static' in file_path:
                data = xlrd.open_workbook(file_path, encoding_override='utf-8')
                table = data.sheets()[0]
                nrows = table.nrows  # 行数
                ncols = table.ncols  # 列数
                row_list = [table.row_values(i) for i in range(0, nrows)]  # 所有行的数据
                col_list = [table.col_values(i) for i in range(0, ncols)]  # 所有列的数
                # 验证参数是否空缺
                index = 1
                err_list = list()
                for i in row_list[1:]:
                    index += 1
                    if not all([i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], i[9]]):
                        err_list.append(str(index))
                if len(err_list) != 0:
                    results['code'] = RET.SERVERERROR
                    m = ""
                    for i in err_list:
                        m = m + i + ','
                    results['msg'] = "第" + m + "行缺少必填参数!"
                    return jsonify(results)

                # 以下是计算服务费
                good_money = col_list[9][1:]
                mail_money_list = col_list[10][1:]
                # 计算全部商品本金
                try:
                    good_sum_money = 0
                    for i in good_money:
                        good_sum_money += float(i)
                    #  计算邮费
                    mail_sum_money = 0
                    for n in mail_money_list:
                        mail_sum_money += float(n)
                except Exception as e:
                    logging.error(e)
                    return jsonify({'code': RET.SERVERERROR, 'msg': '请在商品金额或邮费填写正确信息!'})

                # 计算文字留评数量
                text_review = col_list[11][1:]
                text_num = 0
                for t in text_review:
                    if t.upper() == 'T':
                        text_num += 1

                # 计算图片留评数量
                image_review = col_list[12][1:]
                image_num = 0
                for i in image_review:
                    if i == 'T':
                        image_num += 1

                time_list = col_list[0][1:]
                sunday_num = 0
                for t in time_list:
                    time_str = excel_to_data(t)
                    if date_to_week(time_str) == 6:
                        sunday_num += 1

                # 计算下单数量
                sum_num = len(time_list)

                task_info_list = list()
                for one in row_list[1:]:
                    one_task_list = list()
                    if not one[0]:
                        task_run_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        task_run_time = excel_to_data(one[0])
                    country = one[1]
                    store_name = one[2]
                    key_word = one[3]
                    asin = one[4]
                    good_search_money = float(one[5])
                    good_link = one[6]
                    mail_method = one[7]
                    sku = one[8]
                    good_money = one[9]
                    mail_money = one[10]
                    review_text = one[11]
                    review_image = one[12]
                    one_task_list.append(task_run_time)
                    one_task_list.append(country)
                    one_task_list.append(store_name)
                    one_task_list.append(key_word)
                    one_task_list.append(asin)
                    one_task_list.append(good_search_money)
                    one_task_list.append(good_link)
                    one_task_list.append(mail_method)
                    one_task_list.append(sku)
                    one_task_list.append(good_money)
                    one_task_list.append(mail_money)
                    one_task_list.append(review_text)
                    one_task_list.append(review_image)
                    task_info_list.append(one_task_list)
                task_info_dict = dict()
                task_info_dict['task_info'] = task_info_list

                task_info_dict['sum_num'] = sum_num

                task_info_dict['terrace'] = 'SMT'

                task_info_dict['good_sum_money'] = good_sum_money

                task_info_dict['mail_sum_money'] = mail_sum_money

                task_info_dict['text_num'] = text_num

                task_info_dict['image_num'] = image_num

                task_info_dict['sunday_num'] = sunday_num
                # print(task_info_dict)
                task_info_json = json.dumps(task_info_dict, ensure_ascii=False)
                string = transferContent(task_info_json)
                label = g.cus_label
                SqlData().update_user_cus('task_json', string, user_id, label)

                return jsonify(results)
        except Exception as e:
            logging.error(str(e))
            return '请联系服务商拟定收费规则!'

    else:
        results = {'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR}
        return jsonify(results)


@customer_blueprint.route('/preview', methods=['GET', 'POST'])
@customer_required
def preview_task():
    cus_id = g.cus_id
    results = {'code': RET.OK, 'msg': MSG.OK}
    if request.method == 'GET':
        limit = request.args.get('limit')
        page = request.args.get('page')
        task_json = SqlData().search_cus_field('task_json', cus_id)
        task_dict = json.loads(task_json, strict=False)
        task_list = task_dict.get('task_info')
        data = list()
        for i in task_list:
            one_dict = dict()
            one_dict['country'] = i[0]
            one_dict['task_run_time'] = i[1]
            one_dict['asin'] = i[2]
            one_dict['key_word'] = i[3]
            one_dict['kw_location'] = i[4]
            one_dict['store_name'] = i[5]
            one_dict['good_name'] = i[6]
            one_dict['good_money'] = i[7]
            one_dict['good_link'] = i[8]
            one_dict['pay_method'] = i[9]
            one_dict['serve_class'] = i[10]
            one_dict['mail_method'] = i[11]
            one_dict['note'] = i[12]
            data.append(one_dict)
        page_list = list()
        for i in range(0, len(data), int(limit)):
            page_list.append(data[i:i + int(limit)])
        results['data'] = page_list[int(page) - 1]
        results['count'] = len(data)
        return results


@customer_blueprint.route('/up_task', methods=['GET', 'POST'])
@customer_required
def up_task():
    user_id = g.cus_user_id
    terrace = SqlData().search_user_field('terrace', user_id)
    if terrace != 'AMZ':
        return '此账号没有查看权限!!!'

    if request.method == 'GET':
        return render_template('customer/cus_up_task.html')

    # 预存表格数据到task_json字段中
    if request.method == 'POST':
        cus_id = g.cus_id
        file = request.files.get('file')
        filename = file.filename
        file_path = save_file(file, filename, TASK_DIR)
        results = {'code': RET.OK, 'data': MSG.OK}
        user_id = g.cus_user_id
        try:
            if 'static' in file_path:
                data = xlrd.open_workbook(file_path, encoding_override='utf-8')
                table = data.sheets()[0]
                nrows = table.nrows  # 行数
                ncols = table.ncols  # 列数
                row_list = [table.row_values(i) for i in range(0, nrows)]  # 所有行的数据
                col_list = [table.col_values(i) for i in range(0, ncols)]  # 所有列的数
                # 验证参数是否空缺
                index = 1
                err_list = list()
                for i in row_list[1:]:
                    index += 1
                    if not all([i[0], i[1], i[2], i[3], i[4], i[6], i[7], i[8]]):
                        err_list.append(str(index))
                if len(err_list) != 0:
                    results['code'] = RET.SERVERERROR
                    m = ""
                    for i in err_list:
                        m = m + i + ','
                    results['msg'] = "第" + m + "行缺少必填参数!"
                    return jsonify(results)

                # 验证时间参数是否正确
                run_time_list = col_list[1][1:]
                try:
                    for t in run_time_list:
                        excel_to_data(int(t))
                except Exception as e:
                    logging.error(str(e))
                    return jsonify({'code': RET.SERVERERROR, 'msg': '下单时间格式错误!请按照示例格式填写!'})

                # 验证留评参数是否正确
                review_list = col_list[10][1:]
                for r in review_list:
                    if r not in ['Review', 'FeedBack', 'Review/FeedBack', '']:
                        return jsonify({'code': RET.SERVERERROR, 'msg': '服务类型参数错误:Review(留评), FeedBack(feedba'
                                                                        'ck), Review/FeedBack(留评+feedback), 不做不填'
                                                                        '内容,注意大小写!'})

                # 以下是计算服务费
                asin_list = col_list[2][1:]
                serve_class_list = col_list[10][1:]
                # 计算全部商品本金
                good_money_list = col_list[7][1:]
                good_sum_money = 0
                for i in good_money_list:
                    good_sum_money += float(i)

                # 计算下单数量
                sum_num = len(asin_list)

                # 获取每个asin对饮的数量(字典)
                asin_num_dict = asin_num(asin_list)
                # 去重后的asin列表
                one_asin_list = list(asin_num_dict.keys())
                # 将asin和serve_class组合为列表,数据结构:[['1AJFOAFJA', 'Review/FeedBack'], ['AB', 'FeedBack']]
                asin_group = list()
                index = 0
                for i in asin_list:
                    one_asin = [asin_list[index], serve_class_list[index]]
                    asin_group.append(one_asin)
                    index += 1

                # 计算review的数量和feedback数量
                asin_detail_list = list()
                for asin in one_asin_list:
                    asin_detail = dict()
                    review_num = 0
                    feedback_num = 0
                    for i in asin_group:
                        if i[0] == asin and i[1] == "Review":
                            review_num += 1
                        if i[0] == asin and i[1] == "FeedBack":
                            feedback_num += 1
                        if i[0] == asin and i[1] == "Review/FeedBack":
                            review_num += 1
                            feedback_num += 1
                    asin_detail['asin'] = asin
                    num = asin_num_dict.get(asin)
                    asin_detail['num'] = num
                    asin_detail['review_num'] = review_num
                    asin_detail['feedback'] = feedback_num
                    asin_detail['bili'] = review_num / num
                    asin_detail_list.append(asin_detail)

                # 查询服务商的收费标准
                serve_json = SqlData().search_cus_field('amz_money', cus_id)
                if not serve_json:
                    return jsonify({'code': RET.SERVERERROR, 'msg': "请联系服务商设置收费标准!"})
                else:
                    serve_dict = json.loads(serve_json)
                    feedback = serve_dict.get('feedback')
                    if not feedback:
                        return jsonify({'code': RET.SERVERERROR, 'msg': "请联系服务商设置FeedBack收费标准!"})

                # 判断留评比例是否符合要求
                pass_asin = list()
                for i in asin_detail_list:
                    bili = i.get('bili')
                    bili_baifen = str(int(bili * 100))
                    if bili_baifen in serve_dict:
                        i['review_price'] = serve_dict.get(str(bili_baifen))
                    else:
                        pass_asin.append(i)
                if len(pass_asin) > 0:
                    s = "以下ASIN的留评比例不符合服务商的收费标准: "
                    for i in pass_asin:
                        asin = i.get('asin')
                        bili = str(int(i.get('bili') * 100)) + '%'
                        s1 = asin + ": " + bili + "。 "
                        s += s1
                    s + '更多收费标准请咨询服务商!'
                    return jsonify({'code': RET.SERVERERROR, 'msg': s})

                for i in asin_detail_list:
                    asin_n = i.get('num')
                    price = i.get('review_price')
                    review_money = asin_n * price
                    feedback_num = i.get('feedback')
                    feedback_money = feedback_num * feedback
                    i['sum_money'] = review_money + feedback_money

                task_info_list = list()
                for one in row_list[1:]:
                    one_task_list = list()
                    country = one[0].strip()
                    if not one[1]:
                        task_run_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        task_run_time = excel_to_data(int(one[1]))
                    asin = one[2].strip()
                    key_word = one[3].strip()
                    kw_location = one[4].strip()
                    store_name = one[5].strip()
                    good_name = one[6].strip()
                    good_money = one[7]
                    good_link = one[8].strip()
                    pay_method = one[9].strip()
                    serve_class = one[10].strip()
                    mail_method = one[11].strip()
                    note = one[12].strip()
                    review_title = one[13].strip()
                    review_info = one[14].strip()
                    feedback_info = one[15].strip()
                    one_task_list.append(country)
                    one_task_list.append(task_run_time)
                    one_task_list.append(asin)
                    one_task_list.append(key_word)
                    one_task_list.append(kw_location)
                    one_task_list.append(store_name)
                    one_task_list.append(good_name)
                    one_task_list.append(good_money)
                    one_task_list.append(good_link)
                    one_task_list.append(pay_method)
                    one_task_list.append(serve_class)
                    one_task_list.append(mail_method)
                    one_task_list.append(note)
                    one_task_list.append(review_title)
                    one_task_list.append(review_info)
                    one_task_list.append(feedback_info)
                    task_info_list.append(one_task_list)
                task_info_dict = dict()
                task_info_dict['task_info'] = task_info_list
                serve_money = 0
                for i in asin_detail_list:
                    money = i.get('sum_money')
                    serve_money += money
                task_info_dict['serve_money'] = serve_money

                task_info_dict['good_sum_money'] = good_sum_money

                task_info_dict['terrace'] = 'AMZ'

                task_info_dict['sum_num'] = sum_num
                # print(task_info_dict)
                task_info_json = json.dumps(task_info_dict, ensure_ascii=False)
                string = transferContent(task_info_json)
                label = g.cus_label
                SqlData().update_user_cus('task_json', string, user_id, label)

                return jsonify(results)
        except Exception as e:
            logging.error(str(e))
            results = {'code': RET.SERVERERROR, 'msg': '表格内容错误!请核对表格信息,或咨询服务商表格问题!'}
            return jsonify(results)

    else:
        results = {'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR}
        return jsonify(results)


@customer_blueprint.route('/one_detail/', methods=['GET'])
@customer_required
def one_detail():
    task_code = request.args.get('task_code')
    results = {'code': RET.SERVERERROR, 'msg': MSG.SERVERERROR}
    try:
        i = SqlData().search_order_task_code(task_code)
        print(len(i))
        order_data = dict()
        order_data['big_code'] = i[2].split('-')[0]
        order_data['task_code'] = "\t" + i[2]
        order_data['country'] = i[3]
        order_data['asin'] = "\t" + i[4]
        order_data['key_word'] = i[5]
        order_data['kw_location'] = i[6]
        order_data['store_name'] = i[7]
        order_data['good_name'] = i[8]
        order_data['good_money'] = i[9]
        order_data['good_link'] = i[10]
        order_data['mail_method'] = i[11]
        order_data['pay_method'] = i[12]
        order_data['serve_class'] = i[13]
        order_data['buy_account'] = i[14]
        order_data['account_ps'] = i[15]
        order_data['task_run_time'] = str(i[16])
        order_data['task_state'] = i[17]
        order_data['finish_time'] = str(i[18]) if i[18] else ''
        order_data['brush_hand'] = i[19]
        order_data['order_num'] = "\t" + i[20]
        order_data['good_money_real'] = i[21]
        order_data['taxes_money'] = i[23]
        order_data['note'] = i[25]
        order_data['review_title'] = i[27]
        # if is_json(i[26]):
        #     link_dict = json.loads(i[26])
        #     key_list = list(link_dict.keys())
        #     s = ''
        #     for n in key_list:
        #         s += n
        #     order_data['review_info'] = s
        # else:
        order_data['review_info'] = i[28]
        order_data['feedback_info'] = i[29]
        return render_template('customer/cus_order_detail.html', **order_data)

    except Exception as e:
        logging.error(str(e))
        return jsonify(results)


@customer_blueprint.route('/task_search/', methods=['GET'])
@customer_required
def task_search():
    user_id = g.cus_user_id
    label = g.cus_label
    page = request.args.get('page')
    limit = request.args.get('limit')
    field = request.args.get('field')
    value = request.args.get('value')
    results = {"code": RET.OK, "msg": MSG.OK, "count": 0, "data": ""}
    page_list = list()
    try:
        if value and field:
            state_sql = "AND " + field + "='" + value + "'"
        else:
            return "缺少必要参数!!"
        task_info = SqlData().search_task_field(user_id, label, state_sql=state_sql)
        # task_info = list(reversed(task_info))
        for i in range(0, len(task_info), int(limit)):
            page_list.append(task_info[i:i + int(limit)])
        results['data'] = page_list[int(page) - 1]
        results['count'] = len(task_info)
    except Exception as e:
        logging.warning('没有符合条件的数据' + str(e))
        results['code'] = RET.SERVERERROR
        results['msg'] = MSG.NODATA
    return results


@customer_blueprint.route('/task_detail/', methods=['GET'])
@customer_required
def task_detail():
    sum_order_code = request.args.get('sum_order_code')
    page = request.args.get('page')
    limit = request.args.get('limit')
    task_state = request.args.get('task_state')
    results = {"code": RET.OK, "msg": MSG.OK, "count": 0, "data": ""}
    page_list = list()
    try:
        if task_state:
            state_sql = "AND task_state='" + task_state + "'"
        else:
            state_sql = "AND task_detail_info.task_state!='已完成' AND task_detail_info.task_state!='待留评'"
        task_info = SqlData().search_task_detail(sum_order_code, state_sql=state_sql)
        # task_info = list(reversed(task_info))
        for i in range(0, len(task_info), int(limit)):
            page_list.append(task_info[i:i + int(limit)])
        results['data'] = page_list[int(page) - 1]
        results['count'] = len(task_info)
    except Exception as e:
        logging.warning('没有符合条件的数据' + str(e))
        results['code'] = RET.SERVERERROR
        results['msg'] = MSG.NODATA
    return results


@customer_blueprint.route('/again/', methods=['GET'])
@customer_required
def again():
    sum_order_code = request.args.get('sum_order_code')
    terrace = request.args.get('terrace')
    context = dict()
    context['sum_code'] = sum_order_code
    context['terrace'] = terrace
    if terrace == "AMZ":
        return render_template('customer/again_preview.html', **context)
    if terrace == "SMT":
        return render_template('customer/customer_smt_list.html', **context)


@customer_blueprint.route('/task_list/', methods=['GET'])
@customer_required
def task_list():
    sum_order_code = request.args.get('sum_order_code')
    terrace = request.args.get('terrace')
    context = dict()
    context['sum_code'] = sum_order_code
    context['terrace'] = terrace
    if terrace == "AMZ":
        return render_template('customer/customer_task_list.html', **context)
    if terrace == "SMT":
        return render_template('customer/customer_smt_list.html', **context)


@customer_blueprint.route('/task', methods=['GET'])
@customer_required
def customer_task():
    user_id = g.cus_user_id
    cus_label = g.cus_label
    page = request.args.get('page')
    limit = request.args.get('limit')
    results = {'code': RET.OK, 'msg': MSG.OK}
    sum_order_code = request.args.get('sum_order_code')
    if sum_order_code:
        page = request.args.get('page')
        limit = request.args.get('limit')
        task_info = SqlData().search_task_on_code('sum_order_code', sum_order_code, user_id)
        if len(task_info) == 0:
            return jsonify({'code': RET.OK, 'msg': MSG.NODATA})
        task_info = list(reversed(task_info))
        page_list = list()
        for i in range(0, len(task_info), int(limit)):
            page_list.append(task_info[i:i + int(limit)])
        results['data'] = page_list[int(page) - 1]
        results['count'] = len(task_info)
        return jsonify(results)

    task_info = SqlData().search_task_on_code('customer_label', cus_label, user_id)
    if len(task_info) == 0:
        return jsonify({'code': RET.OK, 'msg': MSG.NODATA})
    task_info = list(reversed(task_info))
    page_list = list()
    for i in range(0, len(task_info), int(limit)):
        page_list.append(task_info[i:i + int(limit)])
    results['data'] = page_list[int(page) - 1]
    results['count'] = len(task_info)
    return jsonify(results)


@customer_blueprint.route('/index', methods=['GET'])
@customer_required
def customer_index():
    context = {'account': g.cus_account}
    return render_template('customer/customer_index.html', **context)


@customer_blueprint.route('/logout', methods=['GET'])
@customer_required
def logout():
    session.pop('cus_id')
    session.pop('customer_label')
    session.pop('customer_account')
    session.pop('customer_discount')
    session.pop('customer_user_id')
    return render_template('customer/login_customer.html')


@customer_blueprint.route('/login', methods=['GET', 'POST'])
def customer_login():
    if request.method == 'GET':
        return render_template('customer/login_customer.html')
    if request.method == 'POST':
        results_er = {'code': RET.SERVERERROR, 'msg': MSG.DATAERROR}
        results_ok = {'code': RET.OK, 'msg': MSG.OK}
        data = json.loads(request.form.get('data'))
        main_user = data.get('main_user')
        account = data.get('account')
        password = data.get('password')
        res = SqlData().search_customer_login(main_user, account, password)
        if not res:
            return jsonify(results_er)
        if res:
            one_info = res[0]
            session['cus_id'] = one_info[0]
            session['customer_account'] = one_info[3]
            session['customer_label'] = one_info[2]
            session['customer_discount'] = one_info[5]
            session['customer_user_id'] = one_info[1]
            return jsonify(results_ok)
